"""出库单服务(销售单×柜双锚定):基于 CONFIRMED SO + OPEN 柜建 DRAFT 出库单
+ 确认出库(唯一扣库存事件,锁内派生可发闸)+ 同事务生成应收款。

核心不变量:
- **可发单一口径**:锁内校验只调 `stock_balance_service.available_by_sku`(复用
  `_balance_subquery`),不另写聚合。available = Σ入库(RECEIVED) − Σ出库(ISSUED)。
- **并发=悲观锁(契约 §2)**:确认出库事务内锁序 **SO 头 → 出库单头**;
  草稿不扣库存,ISSUED 才计。ISSUED 是正向履约终点;0812 退货/冲正单据上线前,
  出库后异常只能走管理员受控线下处理。
- **红线**:出库单/行**无任何价格/成本/售价列**(纯仓单,红线天然隔离);售价侧在
  receivables(整表 RECEIVABLE_READ 门控),不经出库 API 回显。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    NotFoundError,
    OutboundActiveOrderExistsError,
    OutboundDuplicateLineError,
    OutboundInsufficientAvailableError,
    OutboundLineNotInSalesOrderError,
    OutboundOrderEmptyError,
    OutboundOrderInvalidTransitionError,
    OutboundOrderEditConflictError,
    OutboundSalesOrderNotConfirmedError,
    OutboundShipmentNotOpenError,
)
from app.core.statemachine import assert_transition
from app.db.models.outbound_order import (
    OUTBOUND_ORDER_EDITABLE_STATUSES,
    OUTBOUND_ORDER_TRANSITIONS,
    OutboundOrder,
    OutboundOrderLine,
    OutboundOrderStatus,
)
from app.db.models.customer import Customer
from app.db.models.receivable import Receivable
from app.db.models.sales_order import SalesOrder, SalesOrderLine, SalesOrderStatus
from app.db.models.shipment_order import ShipmentOrder, ShipmentOrderStatus
from app.services import stock_balance_service
from app.services.numbering import allocate
from app.services.repo import assert_no_edit_conflict, get_or_404, paginate

_CENT = Decimal("0.01")


async def _next_outbound_no(db: AsyncSession) -> str:
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.OUTBOUND, period)
    return format_code(NumberScope.OUTBOUND, seq, period)


# ---------- 读 ----------


async def get_order(db: AsyncSession, order_id: int) -> OutboundOrder:
    return await get_or_404(db, OutboundOrder, order_id,
                            error_cls=NotFoundError, message=f"出库单不存在: {order_id}")


async def get_order_for_update(db: AsyncSession, order_id: int) -> OutboundOrder:
    return await get_or_404(db, OutboundOrder, order_id, for_update=True,
                            error_cls=NotFoundError, message=f"出库单不存在: {order_id}")


async def list_lines(db: AsyncSession, order_id: int) -> list[OutboundOrderLine]:
    return list((await db.execute(
        select(OutboundOrderLine).where(OutboundOrderLine.outbound_order_id == order_id)
        .order_by(OutboundOrderLine.id))).scalars().all())


async def list_line_views(db: AsyncSession, order_id: int) -> list[dict]:
    """出库行 + 经 join SO 行的展示快照(name/spec/unit;出库行不复制快照,SO 行冻结单一源头)。
    无金额字段。"""
    rows = (await db.execute(
        select(OutboundOrderLine, SalesOrderLine.name_snapshot,
               SalesOrderLine.spec_text_snapshot, SalesOrderLine.unit_snapshot,
               SalesOrderLine.language)
        .join(SalesOrderLine, SalesOrderLine.id == OutboundOrderLine.sales_order_line_id)
        .where(OutboundOrderLine.outbound_order_id == order_id)
        .order_by(OutboundOrderLine.id))).all()
    return [{
        "id": ln.id, "outbound_order_id": ln.outbound_order_id,
        "sales_order_line_id": ln.sales_order_line_id, "sku_id": ln.sku_id,
        "qty": float(ln.qty), "name_snapshot": name, "spec_text_snapshot": spec,
        "unit_snapshot": unit, "language": lang,
    } for (ln, name, spec, unit, lang) in rows]


async def resolve_order_parties(db: AsyncSession, order: OutboundOrder) -> dict:
    """详情投影:来源 SO 号 + 柜号(组柜期可空显 None)+ 柜状态。无红线字段。
    shipment_status 供前端展示柜状态。"""
    so_no = (await db.execute(
        select(SalesOrder.no).where(SalesOrder.id == order.sales_order_id))).scalar_one_or_none()
    ship = (await db.execute(
        select(ShipmentOrder.no, ShipmentOrder.container_no, ShipmentOrder.status)
        .where(ShipmentOrder.id == order.shipment_id))).first()
    return {
        "sales_order_no": so_no or f"#{order.sales_order_id}",
        "shipment_no": ship[0] if ship else f"#{order.shipment_id}",
        "container_no": ship[1] if ship else None,
        "shipment_status": ship[2] if ship else None,
    }


# ---------- 建单 ----------


async def _load_so_lines(db: AsyncSession, sales_order_id: int) -> dict[int, SalesOrderLine]:
    return {ln.id: ln for ln in (await db.execute(
        select(SalesOrderLine).where(
            SalesOrderLine.sales_order_id == sales_order_id))).scalars().all()}


async def _lock_confirmed_so(db: AsyncSession, sales_order_id: int) -> SalesOrder:
    """锁 SO 头 FOR UPDATE 再校验 CONFIRMED(与 SO 取消并发闭环,同型先例=入库锁 PO 头 / 采购锁 SO 头)。"""
    so = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == sales_order_id)
        .with_for_update())).scalar_one_or_none()
    if so is None or so.status != SalesOrderStatus.CONFIRMED:
        raise OutboundSalesOrderNotConfirmedError(f"源 SO 非 CONFIRMED: {sales_order_id}")
    return so


async def _assert_shipment_open(db: AsyncSession, shipment_id: int,
                                *, for_update: bool = False) -> ShipmentOrder:
    """柜须 OPEN,否则 41906。

    for_update=True(建单路径):锁柜头再校验,闭环「建单 × 取消柜」竞态——无锁读会让
    取消柜的活动单 count 与本事务的 INSERT 互不可见,产出「已取消柜下挂活动草稿」。
    锁序 SO 头 → 柜头(cancel_shipment 只锁柜头,不成环)。
    确认/编辑路径无需锁:草稿已提交可见,取消柜被 42001 count 守卫挡住,竞态不存在。"""
    stmt = select(ShipmentOrder).where(ShipmentOrder.id == shipment_id)
    if for_update:
        stmt = stmt.with_for_update()
    ship = (await db.execute(stmt)).scalar_one_or_none()
    if ship is None or ship.status != ShipmentOrderStatus.OPEN:
        raise OutboundShipmentNotOpenError(f"柜非 OPEN: {shipment_id}")
    return ship


async def _assert_no_active_order(db: AsyncSession, shipment_id: int, sales_order_id: int) -> None:
    """同柜同来源 SO 已有活动(非 CANCELLED)出库单 → 41904(service 前置友好报错;
    偏唯一 uq_oborders_shipment_so_active 并发兜底)。"""
    exists = (await db.execute(
        select(func.count(OutboundOrder.id)).where(
            OutboundOrder.shipment_id == shipment_id,
            OutboundOrder.sales_order_id == sales_order_id,
            OutboundOrder.status != OutboundOrderStatus.CANCELLED))).scalar_one()
    if exists > 0:
        raise OutboundActiveOrderExistsError()


def _add_lines(db: AsyncSession, order: OutboundOrder, lines: list[dict],
               so_lines: dict[int, SalesOrderLine]) -> None:
    """新增出库行:sku_id 从 SO 行派生(不采信客户端,天然「sku 与 SO 行一致」);无快照/金额列。"""
    for ln in lines:
        sol = so_lines[ln["sales_order_line_id"]]
        db.add(OutboundOrderLine(
            outbound_order_id=order.id, sales_order_line_id=sol.id,
            sku_id=sol.sku_id, qty=ln["qty"]))


def _validate_lines_in_so(lines: list[dict], so_lines: dict[int, SalesOrderLine]) -> None:
    """行归属 + 单内不重复(一 SO 行一出库行)。前置拒绝给友好错,
    DB UNIQUE(outbound_order_id, sales_order_line_id) 兜底,不让打穿成 500。
    空行兜底(建单/编辑两写入口共守):service 直调放行 0 行会留下占柜槽的空草稿。"""
    if not lines:
        raise OutboundOrderEmptyError()
    seen: set[int] = set()
    for ln in lines:
        line_id = ln["sales_order_line_id"]
        if line_id not in so_lines:
            raise OutboundLineNotInSalesOrderError(f"SO 行 {line_id} 不属于该出库单的 SO")
        if line_id in seen:
            raise OutboundDuplicateLineError(f"SO 行 {line_id} 在 payload 中重复")
        seen.add(line_id)


async def create_order(db: AsyncSession, *, sales_order_id, shipment_id, note,
                       lines: list[dict], actor_user_id, actor_user_email,
                       request: Request | None = None) -> OutboundOrder:
    """基于 CONFIRMED SO + OPEN 柜建一张 DRAFT 出库单(行不跨 SO、不跨柜)。"""
    so = await _lock_confirmed_so(db, sales_order_id)
    await _assert_shipment_open(db, shipment_id, for_update=True)
    await _assert_no_active_order(db, shipment_id, sales_order_id)
    so_lines = await _load_so_lines(db, so.id)
    _validate_lines_in_so(lines, so_lines)

    order = OutboundOrder(
        no=await _next_outbound_no(db), sales_order_id=so.id, shipment_id=shipment_id,
        status=OutboundOrderStatus.DRAFT, note=note, created_by=actor_user_id)
    db.add(order)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        # 偏唯一撞 = 并发建了同柜同 SO 活动单(service 前置查后的窗口);转友好错。
        if "uq_oborders_shipment_so_active" in str(e.orig or e):
            raise OutboundActiveOrderExistsError()
        raise
    _add_lines(db, order, lines, so_lines)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.OUTBOUND_ORDER, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


# ---------- 整单编辑(仅 DRAFT + 乐观锁)----------


async def save_order(db: AsyncSession, *, order_id, note, lines: list[dict],
                     expected_updated_at, actor_user_id, actor_user_email,
                     request: Request | None = None) -> OutboundOrder:
    """整单保存(仅 DRAFT):行整表重写 + 乐观锁。SO/柜 归属不可改(单据身份)。
    先删后加避免复合 UNIQUE(ob_id, so_line_id) 误报。非 DRAFT → 41901(非法转移);
    stale 提交 → 41908(编辑冲突,前端提示刷新,与非法转移分开)。"""
    order = await get_order_for_update(db, order_id)
    if order.status not in OUTBOUND_ORDER_EDITABLE_STATUSES:
        raise OutboundOrderInvalidTransitionError(f"仅草稿出库单可编辑,当前 {order.status}")
    assert_no_edit_conflict(order, expected_updated_at, OutboundOrderEditConflictError)
    so_lines = await _load_so_lines(db, order.sales_order_id)
    _validate_lines_in_so(lines, so_lines)

    order.note = note
    for row in await list_lines(db, order.id):
        await db.delete(row)
    await db.flush()
    _add_lines(db, order, lines, so_lines)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.OUTBOUND_ORDER, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


# ---------- 确认出库(收紧型写入口,契约 §2 锁序 SO头→出库单头)----------


def _compute_receivable_amount(lines: list[OutboundOrderLine],
                               so_lines: dict[int, SalesOrderLine]) -> Decimal:
    """应收原始额 = Σ(行 qty × SO 行 unit_price),逐行 quantize 2dp 再求和。
    舍入模式显式 ROUND_HALF_UP(财务惯例;镜像 payable _compute_payable_amount)。"""
    total = Decimal("0")
    for ln in lines:
        unit_price = Decimal(str(so_lines[ln.sales_order_line_id].unit_price))
        total += (Decimal(str(ln.qty)) * unit_price).quantize(_CENT, rounding=ROUND_HALF_UP)
    return total


async def confirm_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                        request: Request | None = None) -> OutboundOrder:
    """确认出库(DRAFT→ISSUED,唯一扣库存事件)。契约 §2:
    无锁预读身份链 → 锁 SO 头 FOR UPDATE → 锁出库单头 → 转移守卫 → 锁内单一库存闸
    (Σ本单该 sku qty ≤ available(so,sku),不足 41902 带逐 sku 明细)→ ISSUED
    → 同事务建 receivable(偏唯一保幂等)→ 审计 + commit。"""
    # 1. 无锁预读 so_id(sales_order_id 不可变,预读安全)。**列级 select 不实体化**:
    #    若整行实体化,对象进 identity map,后续 get_order_for_update 会返回锁前旧属性
    #    (SQLAlchemy 默认不用新行值覆盖已加载对象),转移守卫读到锁前快照(错题集 A1)。
    pre_so_id = (await db.execute(
        select(OutboundOrder.sales_order_id)
        .where(OutboundOrder.id == order_id))).scalar_one_or_none()
    if pre_so_id is None:
        raise NotFoundError(f"出库单不存在: {order_id}")
    # 2. 锁 SO 头(单 SO,无多头排序问题)。
    so = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == pre_so_id)
        .with_for_update())).scalar_one()
    # 3. 锁出库单头 + 转移守卫。
    order = await get_order_for_update(db, order_id)
    assert_transition(OUTBOUND_ORDER_TRANSITIONS, order.status, OutboundOrderStatus.ISSUED,
                      OutboundOrderInvalidTransitionError)
    if so.status != SalesOrderStatus.CONFIRMED:
        raise OutboundSalesOrderNotConfirmedError()
    await _assert_shipment_open(db, order.shipment_id)
    lines = await list_lines(db, order.id)
    # 确认前兜底空行:0 行出库单会生成 0 金额应收(镜像采购 confirm 的 PurchaseOrderEmptyError)。
    if not lines:
        raise OutboundOrderEmptyError()
    so_lines = await _load_so_lines(db, so.id)
    name_by_sku = {sl.sku_id: sl.name_snapshot for sl in so_lines.values()}

    # 4. 锁内单一库存闸:本单每 sku 需发量 ≤ available(此刻本单仍 DRAFT,不在 outbound 臂计入)。
    need_by_sku: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for ln in lines:
        need_by_sku[ln.sku_id] += Decimal(str(ln.qty))
    available = await stock_balance_service.available_by_sku(
        db, so.id, sku_ids=list(need_by_sku.keys()))
    short = [{
        "sku_id": sku_id, "name_snapshot": name_by_sku.get(sku_id, ""),
        "required_qty": float(need),
        "available_qty": float(available.get(sku_id, Decimal("0"))),
    } for sku_id, need in need_by_sku.items() if need > available.get(sku_id, Decimal("0"))]
    if short:
        raise OutboundInsufficientAvailableError(data={"items": short})

    # 5. 扣减事件成立:ISSUED + issued_at;同事务建 receivable。
    order.status = OutboundOrderStatus.ISSUED
    order.issued_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()

    amount = _compute_receivable_amount(lines, so_lines)
    receivable = Receivable(
        outbound_order_id=order.id, sales_order_id=so.id, customer_id=so.customer_id,
        currency=so.currency, amount_original=amount, amount_allocated=0,
        created_by=actor_user_id)
    db.add(receivable)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        # 活动行偏唯一撞 = 已确认过(并发兜底,头锁下极罕见);转友好非法转移错。
        if "uq_receivables_outbound_active" in str(e.orig or e):
            raise OutboundOrderInvalidTransitionError("出库单已确认,不可重复确认")
        raise
    await write_audit(db, resource_type=AuditResourceType.OUTBOUND_ORDER, action=AuditAction.ISSUE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request,
                      extra={"receivable_id": receivable.id}, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def revert_order(db: AsyncSession, *, order_id, void_reason: str | None, actor_user_id,
                       actor_user_email, request: Request | None = None) -> OutboundOrder:
    """旧撤销出库入口:0811 后出库确认即正向终点,不再允许 ISSUED→DRAFT。

    路由保留用于兼容旧客户端,但统一拒绝;0812 退货/冲正单据上线前,
    出库后异常只能走管理员受控线下处理。"""
    order = await get_order_for_update(db, order_id)
    raise OutboundOrderInvalidTransitionError(
        f"已出库单不可撤销: {order.status};当前系统暂不支持出库后线上冲正,请联系管理员处理")


async def cancel_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> OutboundOrder:
    """取消出库单(仅 DRAFT→CANCELLED;退出偏唯一,同柜同 SO 可重开)。已出库不可取消。"""
    order = await get_order_for_update(db, order_id)
    assert_transition(OUTBOUND_ORDER_TRANSITIONS, order.status, OutboundOrderStatus.CANCELLED,
                      OutboundOrderInvalidTransitionError)
    order.status = OutboundOrderStatus.CANCELLED
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.OUTBOUND_ORDER, action=AuditAction.CANCEL,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


# ---------- 可发行(建单器数据源)----------


async def outboundable_lines(db: AsyncSession, sales_order_id: int) -> list[dict]:
    """某 CONFIRMED SO 的可发行:每行 订购/已入库/已出库/可发 + 展示快照。建单器唯一数据源;
    可发口径复用 compute_stock_balance(单一源头)。无成本/售价字段。"""
    so = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == sales_order_id))).scalar_one_or_none()
    if so is None or so.status != SalesOrderStatus.CONFIRMED:
        raise OutboundSalesOrderNotConfirmedError(f"源 SO 非 CONFIRMED: {sales_order_id}")
    so_lines = list((await db.execute(
        select(SalesOrderLine).where(SalesOrderLine.sales_order_id == sales_order_id)
        .order_by(SalesOrderLine.sort_order))).scalars().all())
    # (SO,SKU) UNIQUE(§0-11)⇒ 每 sku 至多一 SO 行,balance 行按 sku 索引无歧义。
    rows, _ = await stock_balance_service.compute_stock_balance(
        db, sales_order_id=sales_order_id, scope=stock_balance_service.StockScope.ALL)
    by_sku = {r["sku_id"]: r for r in rows}
    out = []
    for ln in so_lines:
        bal = by_sku.get(ln.sku_id)
        out.append({
            "sales_order_line_id": ln.id, "sku_id": ln.sku_id,
            "name_snapshot": ln.name_snapshot, "spec_text_snapshot": ln.spec_text_snapshot,
            "unit_snapshot": ln.unit_snapshot, "language": ln.language,
            "ordered_qty": float(ln.qty),
            "inbound_qty": float(bal["inbound_qty"]) if bal else 0.0,
            "outbound_qty": float(bal["outbound_qty"]) if bal else 0.0,
            "available_qty": float(bal["available_qty"]) if bal else 0.0,
        })
    return out


# ---------- 列表 ----------


async def list_orders(db: AsyncSession, *, status=None, shipment_id=None,
                      sales_order_id=None, keyword=None, page: int = 1,
                      size: int = 20) -> tuple[list[dict], int]:
    """出库单列表:状态 tab / 柜 / SO 过滤 + 关键字(出库单号 / SO 号 / 柜号)+ 分页,
    created_at 降序。投影 SO 号 + 柜号 + 行数/总件数。无金额列。"""
    conds = []
    if status:
        conds.append(OutboundOrder.status == status)
    if shipment_id:
        conds.append(OutboundOrder.shipment_id == shipment_id)
    if sales_order_id:
        conds.append(OutboundOrder.sales_order_id == sales_order_id)
    if keyword:
        like = f"%{keyword}%"
        conds.append(
            OutboundOrder.no.ilike(like) | SalesOrder.no.ilike(like)
            | ShipmentOrder.container_no.ilike(like) | ShipmentOrder.no.ilike(like))

    line_count = (select(func.count(OutboundOrderLine.id))
                  .where(OutboundOrderLine.outbound_order_id == OutboundOrder.id).scalar_subquery())
    total_qty = (select(func.coalesce(func.sum(OutboundOrderLine.qty), 0))
                 .where(OutboundOrderLine.outbound_order_id == OutboundOrder.id).scalar_subquery())

    base = (select(OutboundOrder, SalesOrder.no, ShipmentOrder.no, ShipmentOrder.container_no,
                   Customer.name, line_count.label("lc"), total_qty.label("tq"))
            .join(SalesOrder, SalesOrder.id == OutboundOrder.sales_order_id)
            .join(ShipmentOrder, ShipmentOrder.id == OutboundOrder.shipment_id)
            .join(Customer, Customer.id == SalesOrder.customer_id))
    count_stmt = (select(func.count(OutboundOrder.id))
                  .join(SalesOrder, SalesOrder.id == OutboundOrder.sales_order_id)
                  .join(ShipmentOrder, ShipmentOrder.id == OutboundOrder.shipment_id))
    rows, total = await paginate(
        db, base.where(*conds).order_by(OutboundOrder.created_at.desc()),
        page=page, size=size, count_stmt=count_stmt.where(*conds), scalars=False)
    items = [{
        "id": o.id, "no": o.no, "sales_order_id": o.sales_order_id,
        "sales_order_no": so_no, "shipment_id": o.shipment_id, "shipment_no": sh_no,
        "container_no": container_no, "customer_display": cust_name or f"#{o.sales_order_id}",
        "status": o.status, "issued_at": o.issued_at,
        "line_count": lc, "total_qty": float(tq), "created_at": o.created_at,
    } for (o, so_no, sh_no, container_no, cust_name, lc, tq) in rows]
    return items, total


async def list_related_by_sales_order(db: AsyncSession, sales_order_id: int) -> list[dict]:
    """SO 详情「关联出库单区」:该 SO 下所有出库单(含 CANCELLED 并标状态,可追溯)。"""
    rows = (await db.execute(
        select(OutboundOrder, ShipmentOrder.no, ShipmentOrder.container_no)
        .join(ShipmentOrder, ShipmentOrder.id == OutboundOrder.shipment_id)
        .where(OutboundOrder.sales_order_id == sales_order_id)
        .order_by(OutboundOrder.created_at.desc()))).all()
    return [{
        "id": o.id, "no": o.no, "status": o.status, "shipment_id": o.shipment_id,
        "shipment_no": sh_no, "container_no": container_no, "issued_at": o.issued_at,
    } for (o, sh_no, container_no) in rows]
