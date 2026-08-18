"""入库单服务(ASN 收货):基于 CONFIRMED PO 建入库单 + 超收守卫 + 状态机 + 收货进度派生
+ 创建入库单生成应付款 + 确认入库只产生库存口径。

核心不变量(镜像 purchase_order_service 范式):
- **收货量单一口径**:
  - `compute_inbounded_qty`:某 PO 行的 Σ(非 CANCELLED 入库行 qty,**含在途**)→ **守卫口径**(防重复开 ASN 合计超订)。
  - `compute_received_qty`:某 PO 行的 Σ(**仅 RECEIVED** 入库行 qty)→ **进度/库存口径**(在途不算已收)。
  守卫、PO 详情进度、可收行数据源三处共用此函数族,不各写 SQL(单一源头)。
- **超收守卫** `assert_within_po_line_quota`:同事务内 `SELECT ... FOR UPDATE` 锁 PO 行(额度基准)
  再读聚合再写入。按 po_line_id 升序锁(消死锁环,镜像 _payload_qty_by_poline)。
- **状态转移竞态**:receive/unreceive/cancel/save 一律先锁 inbound 头行 FOR UPDATE 再做守卫。
- **红线**:入库单据零成本列(契约 D3),service 在创建入库单时读 PO 行价算应付额,只落 payables。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.statemachine import assert_transition
from app.core.exceptions import (
    InboundDuplicateLineError,
    InboundFinancialBoundaryError,
    InboundLineNotInPurchaseOrderError,
    InboundOrderEmptyError,
    InboundOrderInvalidTransitionError,
    InboundOrderNotFoundError,
    InboundOverReceiptError,
    InboundSourcePurchaseOrderInvalidError,
)
from app.db.models.inbound_order import (
    INBOUND_ORDER_TRANSITIONS,
    InboundOrder,
    InboundOrderLine,
    InboundOrderStatus,
    ReceiptProgress,
)
from app.db.models.payable import Payable
from app.db.models.purchase_order import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
)
from app.db.models.purchase_return import PurchaseReturnOrder, PurchaseReturnStatus
from app.services.numbering import allocate
from app.services.repo import get_or_404, paginate

_CENT = Decimal("0.01")


async def _next_inbound_no(db: AsyncSession) -> str:
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.INBOUND, period)
    return format_code(NumberScope.INBOUND, seq, period)


# ---------- 收货量单一口径(守卫 / 进度派生 / 可收行共用)----------


async def _sum_inbound_line_qty(db: AsyncSession, po_line_ids: list[int], *,
                                statuses: set[str] | None = None,
                                exclude_inbound_id: int | None = None) -> dict[int, Decimal]:
    """PO 行 → Σ 入库行 qty,按状态过滤。底层单一聚合,守卫/进度口径共用。"""
    result: dict[int, Decimal] = {pid: Decimal("0") for pid in po_line_ids}
    if not po_line_ids:
        return result
    conds = [InboundOrderLine.purchase_order_line_id.in_(po_line_ids)]
    if statuses is not None:
        conds.append(InboundOrder.status.in_(statuses))
    if exclude_inbound_id is not None:
        conds.append(InboundOrderLine.inbound_order_id != exclude_inbound_id)
    rows = (await db.execute(
        select(InboundOrderLine.purchase_order_line_id,
               func.coalesce(func.sum(InboundOrderLine.qty), 0))
        .join(InboundOrder, InboundOrder.id == InboundOrderLine.inbound_order_id)
        .where(*conds)
        .group_by(InboundOrderLine.purchase_order_line_id))).all()
    for pid, s in rows:
        result[pid] = Decimal(str(s))
    return result


async def compute_inbounded_qty(db: AsyncSession, po_line_ids: list[int], *,
                                exclude_inbound_id: int | None = None) -> dict[int, Decimal]:
    """守卫口径:Σ(含在途入库行 qty)。状态集 = InboundOrderStatus.INBOUNDED_STATUSES(单一源头)。
    exclude_inbound_id 排除本单(编辑重算)。"""
    return await _sum_inbound_line_qty(
        db, po_line_ids, statuses=set(InboundOrderStatus.INBOUNDED_STATUSES),
        exclude_inbound_id=exclude_inbound_id)


async def compute_received_qty(db: AsyncSession, po_line_ids: list[int]) -> dict[int, Decimal]:
    """进度/库存口径:Σ(仅 RECEIVED 入库行 qty)。在途不算已收。"""
    return await _sum_inbound_line_qty(
        db, po_line_ids, statuses={InboundOrderStatus.RECEIVED})


def receipt_progress_from(received: dict[int, Decimal], required: dict[int, Decimal]) -> str:
    """由每 PO 行 received/required 派生整单收货进度(唯一口径,列表与详情共用)。
    详情端点已持有行数据与 received 聚合,直接调本函数派生,不再重查(去重复聚合)。"""
    if not required:
        return ReceiptProgress.NOT_RECEIVED
    any_recv = any(received.get(pid, Decimal("0")) > 0 for pid in required)
    all_recv = all(received.get(pid, Decimal("0")) >= req for pid, req in required.items())
    if all_recv:
        return ReceiptProgress.FULLY_RECEIVED
    if any_recv:
        return ReceiptProgress.PARTIALLY_RECEIVED
    return ReceiptProgress.NOT_RECEIVED


async def receipt_progress_for_purchase_orders(
        db: AsyncSession, purchase_order_ids: list[int]) -> dict[int, str]:
    """批量:一组 PO 的收货进度(列表徽标)。一次聚合覆盖全候选集。"""
    if not purchase_order_ids:
        return {}
    rows = (await db.execute(
        select(PurchaseOrderLine.id, PurchaseOrderLine.purchase_order_id, PurchaseOrderLine.qty)
        .where(PurchaseOrderLine.purchase_order_id.in_(purchase_order_ids)))).all()
    received = await compute_received_qty(db, [pid for pid, _, _ in rows])
    required_by_po: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for pid, poid, q in rows:
        required_by_po[poid][pid] = Decimal(str(q))
    return {poid: receipt_progress_from(
        {pid: received.get(pid, Decimal("0")) for pid in required_by_po.get(poid, {})},
        required_by_po.get(poid, {})) for poid in purchase_order_ids}


async def in_transit_inbound_count_for_purchase_orders(
        db: AsyncSession, purchase_order_ids: list[int]) -> dict[int, int]:
    """批量:一组 PO 的在途入库单数(仅 IN_TRANSIT)。列表/选单器次要在途信号。

    与收货进度(实收口径)互补:回答「有几张货在路上未收」,不并入收货态
    (在途货可能被取消/退回,并入会污染收货语义)。已作废/已入库不计。"""
    if not purchase_order_ids:
        return {}
    rows = (await db.execute(
        select(InboundOrder.purchase_order_id, func.count(InboundOrder.id))
        .where(InboundOrder.purchase_order_id.in_(purchase_order_ids),
               InboundOrder.status == InboundOrderStatus.IN_TRANSIT)
        .group_by(InboundOrder.purchase_order_id))).all()
    return {poid: cnt for poid, cnt in rows}


async def has_active_inbound(db: AsyncSession, purchase_order_id: int) -> bool:
    """该 PO 是否存在活动入库单({IN_TRANSIT, RECEIVED})。PO 取消守卫用(契约 D5)。"""
    cnt = (await db.execute(
        select(func.count(InboundOrder.id)).where(
            InboundOrder.purchase_order_id == purchase_order_id,
            InboundOrder.status.in_(
                {InboundOrderStatus.IN_TRANSIT, InboundOrderStatus.RECEIVED})))).scalar_one()
    return cnt > 0


# ---------- 超收守卫(并发安全)----------


async def assert_within_po_line_quota(db: AsyncSession, po_line_id: int, add_qty,
                                      *, exclude_inbound_id: int | None = None) -> None:
    """Σ(非取消入库行 qty,含在途,排除本单) + add_qty ≤ PO 行 qty,否则 41703。

    **并发**:先对目标 purchase_order_lines 行 `SELECT ... FOR UPDATE` 锁住额度基准,再读聚合再写入。
    """
    po_line = (await db.execute(
        select(PurchaseOrderLine).where(PurchaseOrderLine.id == po_line_id)
        .with_for_update())).scalar_one_or_none()
    if po_line is None:
        raise InboundLineNotInPurchaseOrderError(f"PO 行不存在: {po_line_id}")
    inbounded = (await compute_inbounded_qty(
        db, [po_line_id], exclude_inbound_id=exclude_inbound_id))[po_line_id]
    if inbounded + Decimal(str(add_qty)) > Decimal(str(po_line.qty)):
        raise InboundOverReceiptError(
            f"超收:PO 行 {po_line_id} 已入 {inbounded} + 本次 {add_qty} > 额度 {po_line.qty}")


def _payload_qty_by_poline(lines) -> dict[int, Decimal]:
    """按 po_line 聚合本 payload 的入库量(挡「逐行不超但合计超收」;单内结构性单行由 DB 复合 UNIQUE 兜底)。
    **按 po_line_id 升序返回**:守卫循环据此逐行 FOR UPDATE 锁额度基准,统一锁序消死锁环。"""
    agg: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for ln in lines:
        agg[ln["purchase_order_line_id"]] += Decimal(str(ln["qty"]))
    return dict(sorted(agg.items()))


# ---------- 读 ----------


async def get_order(db: AsyncSession, order_id: int) -> InboundOrder:
    return await get_or_404(db, InboundOrder, order_id,
                            error_cls=InboundOrderNotFoundError,
                            message=f"入库单不存在: {order_id}")


async def get_order_for_update(db: AsyncSession, order_id: int) -> InboundOrder:
    return await get_or_404(db, InboundOrder, order_id, for_update=True,
                            error_cls=InboundOrderNotFoundError,
                            message=f"入库单不存在: {order_id}")


async def list_lines(db: AsyncSession, order_id: int) -> list[InboundOrderLine]:
    return list((await db.execute(
        select(InboundOrderLine).where(InboundOrderLine.inbound_order_id == order_id)
        .order_by(InboundOrderLine.sort_order))).scalars().all())


async def get_active_payable(db: AsyncSession, inbound_order_id: int, *,
                             for_update: bool = False) -> Payable | None:
    """该入库单的活动 payable(voided_at IS NULL)。详情 payable 块用(默认不锁)。"""
    stmt = select(Payable).where(
        Payable.inbound_order_id == inbound_order_id, Payable.voided_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _assert_no_active_reverse_order(db: AsyncSession, inbound_order_id: int) -> None:
    exists = (await db.execute(
        select(PurchaseReturnOrder.id)
        .where(
            PurchaseReturnOrder.inbound_order_id == inbound_order_id,
            PurchaseReturnOrder.status.in_({
                PurchaseReturnStatus.PENDING_APPROVAL,
                PurchaseReturnStatus.APPROVED,
            }),
        )
        .limit(1))).scalar_one_or_none()
    if exists is not None:
        raise InboundFinancialBoundaryError(
            "入库单已有待处理逆向单据,不可确认入库;请先完成或驳回该逆向单据")


# ---------- 建单 ----------


async def _lock_confirmed_po(db: AsyncSession, purchase_order_id: int) -> PurchaseOrder:
    """锁 PO 头行 FOR UPDATE 再校验 CONFIRMED(与 PO 取消并发闭环:锁序统一 PO 头 → PO 行)。"""
    po = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == purchase_order_id)
        .with_for_update())).scalar_one_or_none()
    if po is None or po.status != PurchaseOrderStatus.CONFIRMED:
        raise InboundSourcePurchaseOrderInvalidError(f"源 PO 无效: {purchase_order_id}")
    return po


async def _load_po_lines(db: AsyncSession, purchase_order_id: int) -> dict[int, PurchaseOrderLine]:
    return {ln.id: ln for ln in (await db.execute(
        select(PurchaseOrderLine).where(
            PurchaseOrderLine.purchase_order_id == purchase_order_id))).scalars().all()}


def _validate_lines_in_po(lines: list[dict], po_lines: dict[int, PurchaseOrderLine],
                          purchase_order_id: int) -> None:
    """行归属 + 单内不重复(一 PO 行一入库行)。前置拒绝给友好错,
    DB UNIQUE(inbound_order_id, purchase_order_line_id) 兜底,不让打穿成 500(镜像出库侧)。"""
    seen: set[int] = set()
    for ln in lines:
        line_id = ln["purchase_order_line_id"]
        if line_id not in po_lines:
            raise InboundLineNotInPurchaseOrderError(
                f"PO 行 {line_id} 不属于 PO {purchase_order_id}")
        if line_id in seen:
            raise InboundDuplicateLineError(f"PO 行 {line_id} 在 payload 中重复")
        seen.add(line_id)


def _add_lines(db: AsyncSession, order: InboundOrder, lines: list[dict],
               po_lines: dict[int, PurchaseOrderLine]) -> None:
    """新增入库行:平移 PO 行快照(收的就是订的),qty 本次录入。无金额列。"""
    for idx, ln in enumerate(lines):
        pol = po_lines[ln["purchase_order_line_id"]]
        db.add(InboundOrderLine(
            inbound_order_id=order.id, purchase_order_line_id=pol.id, sku_id=pol.sku_id,
            name_snapshot=pol.name_snapshot, spec_text_snapshot=pol.spec_text_snapshot,
            unit_snapshot=pol.unit_snapshot, language=pol.language, qty=ln["qty"],
            sort_order=ln.get("sort_order", idx), remark=ln.get("remark")))


async def _compute_payable_amount(db: AsyncSession, order: InboundOrder,
                                  po_lines: dict[int, PurchaseOrderLine]) -> Decimal:
    """应付原始额 = Σ(行 qty × PO 行 unit_price),逐行 quantize 2dp 再求和。
    舍入模式显式 ROUND_HALF_UP(财务四舍五入惯例;不写则吃 Decimal 上下文默认 half-even)。"""
    total = Decimal("0")
    for ln in await list_lines(db, order.id):
        unit_price = Decimal(str(po_lines[ln.purchase_order_line_id].unit_price))
        total += (Decimal(str(ln.qty)) * unit_price).quantize(_CENT, rounding=ROUND_HALF_UP)
    return total


async def _create_payable_for_order(db: AsyncSession, order: InboundOrder,
                                    po: PurchaseOrder,
                                    po_lines: dict[int, PurchaseOrderLine],
                                    actor_user_id: int) -> Payable:
    """创建入库单即成立供应商应付。入库单/行不落成本,账层单独承载金额。"""
    amount = await _compute_payable_amount(db, order, po_lines)
    payable = Payable(
        inbound_order_id=order.id, purchase_order_id=po.id, supplier_id=po.supplier_id,
        currency=po.currency, amount_original=amount, amount_allocated=0,
        created_by=actor_user_id)
    db.add(payable)
    await db.flush()
    return payable


async def create_order(db: AsyncSession, *, purchase_order_id, carrier_name, tracking_no,
                       shipped_at, eta, remark, lines: list[dict], actor_user_id,
                       actor_user_email, request: Request | None = None) -> InboundOrder:
    """基于 CONFIRMED PO 建一张 IN_TRANSIT 入库单,平移 PO 行快照。"""
    if not lines:
        raise InboundOrderEmptyError()
    po = await _lock_confirmed_po(db, purchase_order_id)
    po_lines = await _load_po_lines(db, purchase_order_id)
    _validate_lines_in_po(lines, po_lines, purchase_order_id)
    # 超收守卫:按 po_line 聚合本 payload 量,逐 po_line 校验(FOR UPDATE 锁额度基准)
    for po_line_id, add_qty in _payload_qty_by_poline(lines).items():
        await assert_within_po_line_quota(db, po_line_id, add_qty)

    order = InboundOrder(
        no=await _next_inbound_no(db), purchase_order_id=purchase_order_id,
        status=InboundOrderStatus.IN_TRANSIT, carrier_name=carrier_name,
        tracking_no=tracking_no, shipped_at=shipped_at, eta=eta, remark=remark,
        created_by=actor_user_id)
    db.add(order)
    await db.flush()
    _add_lines(db, order, lines, po_lines)
    await db.flush()
    payable = await _create_payable_for_order(db, order, po, po_lines, actor_user_id)
    await write_audit(db, resource_type=AuditResourceType.INBOUND_ORDER, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request,
                      extra={"payable_id": payable.id}, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


# ---------- 整单编辑收口 ----------


async def save_order(db: AsyncSession, *, order_id, carrier_name, tracking_no, shipped_at,
                     eta, remark, lines: list[dict], expected_updated_at, actor_user_id,
                     actor_user_email, request: Request | None = None) -> InboundOrder:
    """创建入库单即产生应付,整单编辑已收口到后续逆向/调整流程。"""
    await get_order_for_update(db, order_id)
    raise InboundFinancialBoundaryError(
        "创建入库单后已产生供应商应付,不可直接编辑入库单;请走履约中取消/调整流程")


# ---------- 状态跃迁 ----------


async def receive_order(db: AsyncSession, *, order_id, arrived_at: date | None, actor_user_id,
                        actor_user_email, request: Request | None = None) -> InboundOrder:
    """确认入库(IN_TRANSIT→RECEIVED)。只确认库存事实,不再生成 payable。"""
    from app.services import stock_ledger_service

    impacts = await stock_ledger_service.inbound_impacts(db, order_id)
    await stock_ledger_service.lock_sales_orders(db, [i.sales_order_id for i in impacts])
    order = await get_order_for_update(db, order_id)
    assert_transition(INBOUND_ORDER_TRANSITIONS, order.status, InboundOrderStatus.RECEIVED,
                      InboundOrderInvalidTransitionError)
    await _assert_no_active_reverse_order(db, order.id)
    lines = await list_lines(db, order.id)
    if not lines:
        raise InboundOrderEmptyError()
    order.status = InboundOrderStatus.RECEIVED
    # 兜底默认 = UTC 当天(全仓时间一律 UTC;前端确认框恒显式传日期,此默认仅直调 API 时触达。
    # 不引入业务时区配置——无第二个消费者,属过度设计)。
    order.arrived_at = arrived_at or datetime.now(timezone.utc).date()
    await db.flush()
    await stock_ledger_service.record_inbound_receive(
        db, inbound_order_id=order.id, occurred_at=None, actor_user_id=actor_user_id)

    payable = await get_active_payable(db, order.id)
    await write_audit(db, resource_type=AuditResourceType.INBOUND_ORDER, action=AuditAction.RECEIVE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request,
                      extra={"payable_id": payable.id if payable is not None else None}, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def unreceive_order(db: AsyncSession, *, order_id, void_reason: str | None, actor_user_id,
                          actor_user_email, request: Request | None = None) -> InboundOrder:
    """撤销入库(RECEIVED→IN_TRANSIT)。只撤销库存事实,不作废应付。

    **收紧型写入口(库存契约 §2,还债)**:货可能已被出库消费,撤回将使某 (SO, SKU) 可发
    穿仓(available < 0)。故按契约锁序补校验:
      1. 无锁预读入库行→PO 行→SO 行链,取受影响 (so_id → {sku_id}) 与 distinct so_ids(按 id 排序);
      2. 依序锁各 SO 头 FOR UPDATE(统一锁序消死锁环)→ 再锁入库单头(锁序合规);
      3. 转移守卫,状态翻转 IN_TRANSIT 并 flush;
      4. **锁内派生校验**:翻转后受影响每 (so,sku) 的 available ≥ 0,违反 → 41710。
    应付在创建入库单时已成立,撤销入库不再作废账行。"""
    from app.services import stock_ledger_service

    impacts = await stock_ledger_service.inbound_impacts(db, order_id)
    so_ids = sorted({i.sales_order_id for i in impacts})

    # 2. 依序锁 SO 头(按 id 升序,统一锁序)→ 再锁入库单头。
    await stock_ledger_service.lock_sales_orders(db, so_ids)
    order = await get_order_for_update(db, order_id)

    # 3. 转移前做余额穿仓校验,再翻转状态并写库存冲回流水。
    assert_transition(INBOUND_ORDER_TRANSITIONS, order.status, InboundOrderStatus.IN_TRANSIT,
                      InboundOrderInvalidTransitionError)
    await _assert_no_active_reverse_order(db, order.id)
    await stock_ledger_service.assert_can_unreceive_inbound(db, order.id)
    payable = await get_active_payable(db, order.id)
    order.status = InboundOrderStatus.IN_TRANSIT
    order.arrived_at = None  # 回在途即未到货:清到货日,与状态语义一致(重收时重新填)
    await db.flush()
    await stock_ledger_service.record_inbound_unreceive(
        db, inbound_order_id=order.id, actor_user_id=actor_user_id, note=void_reason)

    await write_audit(db, resource_type=AuditResourceType.INBOUND_ORDER,
                      action=AuditAction.UNRECEIVE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=order.id, request=request,
                      extra={"payable_id": payable.id if payable is not None else None,
                             "unreceive_check_ok": True}, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def cancel_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> InboundOrder:
    """作废入库单已收口:创建入库单即产生应付,不可裸作废回退。"""
    await get_order_for_update(db, order_id)
    raise InboundFinancialBoundaryError(
        "创建入库单后已产生供应商应付,不可直接作废;请走采购退货、供应商贷项单等真实逆向单据")


# ---------- 可收行(建单器数据源)----------


async def receivable_lines(db: AsyncSession, purchase_order_id: int) -> list[dict]:
    """某 CONFIRMED PO 的可收行:每行 {订购/在途/已入/剩余}。建单器唯一数据源;无成本字段。"""
    po = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == purchase_order_id))).scalar_one_or_none()
    if po is None or po.status != PurchaseOrderStatus.CONFIRMED:
        raise InboundSourcePurchaseOrderInvalidError(f"源 PO 无效: {purchase_order_id}")
    po_lines = list((await db.execute(
        select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == purchase_order_id)
        .order_by(PurchaseOrderLine.sort_order))).scalars().all())
    ids = [ln.id for ln in po_lines]
    inbounded = await compute_inbounded_qty(db, ids)   # 含在途 = 守卫口径
    received = await compute_received_qty(db, ids)      # 仅已入
    out = []
    for ln in po_lines:
        ordered = Decimal(str(ln.qty))
        inb = inbounded.get(ln.id, Decimal("0"))
        rcv = received.get(ln.id, Decimal("0"))
        out.append({
            "purchase_order_line_id": ln.id, "sku_id": ln.sku_id,
            "name_snapshot": ln.name_snapshot, "spec_text_snapshot": ln.spec_text_snapshot,
            "unit_snapshot": ln.unit_snapshot, "language": ln.language,
            "ordered_qty": float(ordered),
            "in_transit_qty": float(inb - rcv),   # 非取消含在途 − 已入 = 纯在途
            "received_qty": float(rcv),
            "remaining_qty": float(ordered - inb),   # 剩余可开 = 订购 − 守卫口径
        })
    return out


# ---------- 列表 ----------


async def list_orders(db: AsyncSession, *, status=None, purchase_order_id=None, supplier_id=None,
                      keyword=None, page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """入库单列表:状态 tab / PO / 供应商过滤 + 关键字(no / tracking_no / PO no)+ 分页,created_at 降序。
    投影 PO 号 + 供应商展示名 + 行数/总数量。无金额列。"""
    conds = []
    if status:
        conds.append(InboundOrder.status == status)
    if purchase_order_id:
        conds.append(InboundOrder.purchase_order_id == purchase_order_id)
    if supplier_id:
        conds.append(PurchaseOrder.supplier_id == supplier_id)
    if keyword:
        like = f"%{keyword}%"
        conds.append(
            InboundOrder.no.ilike(like) | InboundOrder.tracking_no.ilike(like)
            | PurchaseOrder.no.ilike(like))

    line_count = (select(func.count(InboundOrderLine.id))
                  .where(InboundOrderLine.inbound_order_id == InboundOrder.id).scalar_subquery())
    total_qty = (select(func.coalesce(func.sum(InboundOrderLine.qty), 0))
                 .where(InboundOrderLine.inbound_order_id == InboundOrder.id).scalar_subquery())

    from app.db.models.supplier import Supplier
    base = (select(InboundOrder, PurchaseOrder.no, Supplier.name,
                   line_count.label("lc"), total_qty.label("tq"))
            .join(PurchaseOrder, PurchaseOrder.id == InboundOrder.purchase_order_id)
            .join(Supplier, Supplier.id == PurchaseOrder.supplier_id))
    count_stmt = (select(func.count(InboundOrder.id))
                  .join(PurchaseOrder, PurchaseOrder.id == InboundOrder.purchase_order_id))
    rows, total = await paginate(
        db, base.where(*conds).order_by(InboundOrder.created_at.desc()),
        page=page, size=size, count_stmt=count_stmt.where(*conds), scalars=False)
    items = [{
        "id": o.id, "no": o.no, "purchase_order_id": o.purchase_order_id,
        "purchase_order_no": po_no, "supplier_display": sup_name, "status": o.status,
        "carrier_name": o.carrier_name, "tracking_no": o.tracking_no, "eta": o.eta,
        "arrived_at": o.arrived_at, "line_count": lc, "total_qty": float(tq),
        "created_at": o.created_at,
    } for (o, po_no, sup_name, lc, tq) in rows]
    return items, total


async def list_related_by_purchase_order(db: AsyncSession, purchase_order_id: int) -> list[dict]:
    """PO 详情「入库记录区」:该 PO 下所有入库单(含 CANCELLED 并标状态,可追溯)。"""
    rows = (await db.execute(
        select(InboundOrder).where(InboundOrder.purchase_order_id == purchase_order_id)
        .order_by(InboundOrder.created_at.desc()))).scalars().all()
    return [{
        "id": o.id, "no": o.no, "status": o.status, "carrier_name": o.carrier_name,
        "tracking_no": o.tracking_no, "eta": o.eta, "arrived_at": o.arrived_at,
        "created_at": o.created_at,
    } for o in rows]
