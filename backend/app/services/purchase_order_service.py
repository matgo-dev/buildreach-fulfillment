"""采购单服务(按单采购):基于 SO 建 PO + 超采守卫 + 状态机 + 采购进度派生。

核心不变量:
- **覆盖度单一口径** `compute_covered_qty`:某 SO 行的 covered = Σ(非 CANCELLED PO 行 qty,**含 DRAFT**)。
  守卫(超采)、列表进度派生、详情 covered_qty 三处共用此一函数,不各写 SQL(单一源头)。
- **超采守卫** `assert_within_so_line_quota`:同事务内 `SELECT ... FOR UPDATE` 锁 SO 行(额度基准)
  再读聚合再写入——否则两个并发 CREATE 各自事务读不到对方、双草稿可合计超额。并发假设显式落注释。
- **红线**:采购价/金额脱敏在响应 schema 构造工厂(schemas/purchase_order.py),service 只算真值。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.statemachine import assert_transition
from app.core.exceptions import (
    PurchaseOrderEditConflictError,
    PurchaseOrderEmptyError,
    PurchaseOrderInvalidTransitionError,
    PurchaseOrderNotDraftError,
    PurchaseOrderNotFoundError,
    PurchaseOrderSupplierInactiveError,
    PurchaseOverQuotaError,
    PurchaseSourceSalesOrderInvalidError,
    SupplierNotFoundError,
)
from app.db.models.purchase_order import (
    PURCHASE_ORDER_DELETABLE_STATUSES,
    PURCHASE_ORDER_EDITABLE_STATUSES,
    PURCHASE_ORDER_TRANSITIONS,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    PurchaseProgress,
)
from app.db.models.sales_order import SalesOrder, SalesOrderLine, SalesOrderStatus
from app.db.models.sku import Sku
from app.db.models.supplier import Supplier, SupplierStatus
from app.services.numbering import allocate
from app.services.repo import assert_no_edit_conflict, get_or_404, paginate


async def _next_po_no(db: AsyncSession) -> str:
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.PURCHASE_ORDER, period)
    return format_code(NumberScope.PURCHASE_ORDER, seq, period)


# ---------- 覆盖度单一口径(守卫 / 进度派生 / 详情共用)----------


async def compute_covered_qty(db: AsyncSession, so_line_ids: list[int], *,
                              exclude_po_id: int | None = None) -> dict[int, Decimal]:
    """SO 行 → 已覆盖数量。covered = Σ(非 CANCELLED PO 行 qty,含 DRAFT)。
    exclude_po_id:重算某 PO 自身额度时排除它(编辑/确认重校验,避免把自己的行重复计入)。"""
    result: dict[int, Decimal] = {sid: Decimal("0") for sid in so_line_ids}
    if not so_line_ids:
        return result
    conds = [
        PurchaseOrderLine.source_sales_order_line_id.in_(so_line_ids),
        PurchaseOrder.status != PurchaseOrderStatus.CANCELLED,
    ]
    if exclude_po_id is not None:
        conds.append(PurchaseOrderLine.purchase_order_id != exclude_po_id)
    rows = (await db.execute(
        select(PurchaseOrderLine.source_sales_order_line_id,
               func.coalesce(func.sum(PurchaseOrderLine.qty), 0))
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(*conds)
        .group_by(PurchaseOrderLine.source_sales_order_line_id))).all()
    for sid, covered in rows:
        result[sid] = Decimal(str(covered))
    return result


def _progress_from(covered: dict[int, Decimal], required: dict[int, Decimal]) -> str:
    """由每行 covered/required 派生整单进度(唯一口径,列表与详情共用)。"""
    if not required:
        return PurchaseProgress.NOT_ORDERED
    any_covered = any(covered.get(sid, Decimal("0")) > 0 for sid in required)
    all_covered = all(covered.get(sid, Decimal("0")) >= req for sid, req in required.items())
    if all_covered:
        return PurchaseProgress.FULLY_ORDERED
    if any_covered:
        return PurchaseProgress.PARTIALLY_ORDERED
    return PurchaseProgress.NOT_ORDERED


async def compute_progress(db: AsyncSession, sales_order_id: int) -> tuple[str, dict[int, Decimal]]:
    """整单采购进度 + 每 SO 行 covered_qty(详情用)。共用 compute_covered_qty。"""
    so_lines = list((await db.execute(
        select(SalesOrderLine.id, SalesOrderLine.qty)
        .where(SalesOrderLine.sales_order_id == sales_order_id))).all())
    required = {lid: Decimal(str(q)) for lid, q in so_lines}
    covered = await compute_covered_qty(db, list(required.keys()))
    return _progress_from(covered, required), covered


async def progress_for_sales_orders(db: AsyncSession, sales_order_ids: list[int]) -> dict[int, str]:
    """批量:一组 SO 的采购进度(列表徽标 + 筛选用)。共用 compute_covered_qty 单一口径,
    一次聚合覆盖全候选集(非逐 SO 查),供 SO 列表在「算进度→过滤→分页」中作 DB 派生值。"""
    if not sales_order_ids:
        return {}
    rows = (await db.execute(
        select(SalesOrderLine.id, SalesOrderLine.sales_order_id, SalesOrderLine.qty)
        .where(SalesOrderLine.sales_order_id.in_(sales_order_ids)))).all()
    covered = await compute_covered_qty(db, [lid for lid, _, _ in rows])
    required_by_so: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for lid, soid, q in rows:
        required_by_so[soid][lid] = Decimal(str(q))
    return {soid: _progress_from(
        {lid: covered.get(lid, Decimal("0")) for lid in required_by_so.get(soid, {})},
        required_by_so.get(soid, {})) for soid in sales_order_ids}


# ---------- 超采守卫(并发安全)----------


async def assert_within_so_line_quota(db: AsyncSession, so_line_id: int, add_qty,
                                      *, exclude_po_id: int | None = None) -> None:
    """Σ(非取消 PO 行 qty,排除本单) + add_qty ≤ SO 行 qty,否则 41603。

    **并发**:先对目标 sales_order_lines 行 `SELECT ... FOR UPDATE` 锁住额度基准,再读聚合再写入。
    不隐式依赖「内部低并发」——两个并发 CREATE 若不锁,各自读不到对方的草稿,双草稿可合计超额。
    """
    so_line = (await db.execute(
        select(SalesOrderLine).where(SalesOrderLine.id == so_line_id)
        .with_for_update())).scalar_one_or_none()
    if so_line is None:
        raise PurchaseSourceSalesOrderInvalidError(f"SO 行不存在: {so_line_id}")
    covered = (await compute_covered_qty(
        db, [so_line_id], exclude_po_id=exclude_po_id))[so_line_id]
    if covered + Decimal(str(add_qty)) > Decimal(str(so_line.qty)):
        raise PurchaseOverQuotaError(
            f"超采:SO 行 {so_line_id} 已覆盖 {covered} + 本次 {add_qty} > 额度 {so_line.qty}")


# ---------- 读 ----------


async def get_order(db: AsyncSession, order_id: int) -> PurchaseOrder:
    return await get_or_404(db, PurchaseOrder, order_id,
                            error_cls=PurchaseOrderNotFoundError,
                            message=f"采购单不存在: {order_id}")


async def get_order_for_update(db: AsyncSession, order_id: int) -> PurchaseOrder:
    return await get_or_404(db, PurchaseOrder, order_id, for_update=True,
                            error_cls=PurchaseOrderNotFoundError,
                            message=f"采购单不存在: {order_id}")


async def list_lines(db: AsyncSession, order_id: int) -> list[PurchaseOrderLine]:
    return list((await db.execute(
        select(PurchaseOrderLine).where(PurchaseOrderLine.purchase_order_id == order_id)
        .order_by(PurchaseOrderLine.sort_order))).scalars().all())


async def resolve_order_parties(db: AsyncSession, po: PurchaseOrder) -> dict:
    """详情投影:供应商展示名 + 来源 SO 号。"""
    sup = (await db.execute(
        select(Supplier.name).where(Supplier.id == po.supplier_id))).scalar_one_or_none()
    so_no = (await db.execute(
        select(SalesOrder.no).where(SalesOrder.id == po.source_sales_order_id))).scalar_one_or_none()
    return {
        "supplier_display": sup or f"#{po.supplier_id}",
        "source_sales_order_no": so_no or f"#{po.source_sales_order_id}",
    }


# ---------- 建单 ----------


async def _load_source_so_lines(db: AsyncSession, source_sales_order_id: int) -> dict[int, SalesOrderLine]:
    """取源 SO(须 CONFIRMED)的行,按行 id 索引。SO 无效 → 41604。

    锁 SO 头行 FOR UPDATE 再校验(与 SO 取消并发闭环,评审 B2;同型先例=入库锁 PO 头):
    不锁则「读到 CONFIRMED → 取消事务提交 → 本事务插单」交错会把活动 PO 挂到 CANCELLED SO 上。
    锁序:建单 SO头→SO行;取消 SO头→报价头;convert 仅报价头——无环无死锁。"""
    so = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == source_sales_order_id)
        .with_for_update())).scalar_one_or_none()
    if so is None or so.status != SalesOrderStatus.CONFIRMED:
        raise PurchaseSourceSalesOrderInvalidError(f"源 SO 无效: {source_sales_order_id}")
    return {ln.id: ln for ln in (await db.execute(
        select(SalesOrderLine).where(
            SalesOrderLine.sales_order_id == source_sales_order_id))).scalars().all()}


async def _assert_supplier_active(db: AsyncSession, supplier_id: int) -> Supplier:
    sup = (await db.execute(
        select(Supplier).where(Supplier.id == supplier_id))).scalar_one_or_none()
    if sup is None:
        raise SupplierNotFoundError(f"供应商不存在: {supplier_id}")
    if sup.status != SupplierStatus.ACTIVE:
        raise PurchaseOrderSupplierInactiveError()
    return sup


def _payload_qty_by_soline(lines) -> dict[int, Decimal]:
    """按 so_line 聚合本 payload 的采购量(挡「逐行不超但合计超采」;PO 内结构性单行由 DB 复合 UNIQUE 兜底)。

    **按 so_line_id 升序返回**:下游三处守卫循环据此逐行 `FOR UPDATE` 锁额度基准,统一锁序 =
    任意两个并发事务永远同序取锁,消除「事务1锁A等B、事务2锁B等A」的死锁环(全局锁序标准手法)。
    """
    agg: dict[int, Decimal] = defaultdict(lambda: Decimal("0"))
    for ln in lines:
        agg[ln["source_sales_order_line_id"]] += Decimal(str(ln["qty"]))
    return dict(sorted(agg.items()))


async def create_order(db: AsyncSession, *, source_sales_order_id, supplier_id, currency,
                       remark, lines: list[dict], actor_user_id, actor_user_email,
                       request: Request | None = None) -> PurchaseOrder:
    """基于 CONFIRMED SO 建一张 DRAFT PO(单一供应商),平移 SO 行快照,采购价全新录入。"""
    if not lines:
        raise PurchaseOrderEmptyError()
    so_lines = await _load_source_so_lines(db, source_sales_order_id)
    await _assert_supplier_active(db, supplier_id)
    # 每行 so_line 必须属于该 SO
    for ln in lines:
        if ln["source_sales_order_line_id"] not in so_lines:
            raise PurchaseSourceSalesOrderInvalidError(
                f"SO 行 {ln['source_sales_order_line_id']} 不属于 SO {source_sales_order_id}")
    # 超采守卫:按 so_line 聚合本 payload 量,逐 so_line 校验(FOR UPDATE 锁额度基准)
    for so_line_id, add_qty in _payload_qty_by_soline(lines).items():
        await assert_within_so_line_quota(db, so_line_id, add_qty)

    po = PurchaseOrder(
        no=await _next_po_no(db), source_sales_order_id=source_sales_order_id,
        supplier_id=supplier_id, currency=currency, status=PurchaseOrderStatus.DRAFT,
        total_amount=0, remark=remark, created_by=actor_user_id)
    db.add(po)
    await db.flush()
    total = _add_lines(db, po, lines, so_lines)
    po.total_amount = total
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.PURCHASE_ORDER, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=po.id, request=request, commit=False)
    await db.commit()
    await db.refresh(po)
    return po


def _add_lines(db: AsyncSession, po: PurchaseOrder, lines: list[dict],
               so_lines: dict[int, SalesOrderLine]) -> Decimal:
    """新增 PO 行:平移 SO 行快照,采购价录入,line_total=Decimal 精度。返回 Σ line_total。"""
    total = Decimal("0")
    for idx, ln in enumerate(lines):
        sol = so_lines[ln["source_sales_order_line_id"]]
        line_total = Decimal(str(ln["unit_price"])) * Decimal(str(ln["qty"]))
        total += line_total
        db.add(PurchaseOrderLine(
            purchase_order_id=po.id, sku_id=sol.sku_id,
            source_sales_order_line_id=sol.id,
            name_snapshot=sol.name_snapshot, spec_text_snapshot=sol.spec_text_snapshot,
            unit_snapshot=sol.unit_snapshot, unit_price=ln["unit_price"], qty=ln["qty"],
            line_total=line_total, language=sol.language,
            sort_order=ln.get("sort_order", idx), remark=ln.get("remark")))
    return total


# ---------- 整单编辑(仅 DRAFT + 乐观锁 + 对账)----------


async def save_order(db: AsyncSession, *, order_id, supplier_id, currency, remark,
                     lines: list[dict], expected_updated_at, actor_user_id, actor_user_email,
                     request: Request | None = None) -> PurchaseOrder:
    """整单保存草稿:按行 id 对账(增/改/删)+ 乐观锁 + 超采重校验。source SO 不可改。
    对账**先删后加**同事务落库,避免复合 UNIQUE(po_id,so_line_id) 在「先加撞旧行」时误报。"""
    po = await get_order_for_update(db, order_id)
    if po.status not in PURCHASE_ORDER_EDITABLE_STATUSES:
        raise PurchaseOrderNotDraftError()
    assert_no_edit_conflict(po, expected_updated_at, PurchaseOrderEditConflictError)
    if not lines:
        raise PurchaseOrderEmptyError()

    so_lines = await _load_source_so_lines(db, po.source_sales_order_id)
    for ln in lines:
        if ln["source_sales_order_line_id"] not in so_lines:
            raise PurchaseSourceSalesOrderInvalidError(
                f"SO 行 {ln['source_sales_order_line_id']} 不属于 SO {po.source_sales_order_id}")
    # 超采重校验(排除本 PO 现有行,按 so_line 聚合新 payload)
    for so_line_id, add_qty in _payload_qty_by_soline(lines).items():
        await assert_within_so_line_quota(db, so_line_id, add_qty, exclude_po_id=po.id)

    supplier_id_changed = po.supplier_id != supplier_id
    if supplier_id_changed:
        await _assert_supplier_active(db, supplier_id)
    po.supplier_id, po.currency, po.remark = supplier_id, currency, remark

    # 先删后加:清空现行再按 payload 重建(payload 均视为期望态;PO 行是廉价快照,整表重写最简单可靠)
    for row in await list_lines(db, po.id):
        await db.delete(row)
    await db.flush()
    po.total_amount = _add_lines(db, po, lines, so_lines)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.PURCHASE_ORDER, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=po.id, request=request, commit=False)
    await db.commit()
    await db.refresh(po)
    return po


# ---------- 状态跃迁 ----------


async def confirm_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                        request: Request | None = None) -> PurchaseOrder:
    """DRAFT→CONFIRMED(下单)。确认前:至少 1 行 + 超采重校验(防并发草稿抢额度)。"""
    po = await get_order_for_update(db, order_id)
    assert_transition(PURCHASE_ORDER_TRANSITIONS, po.status, PurchaseOrderStatus.CONFIRMED,
                      PurchaseOrderInvalidTransitionError)
    lines = await list_lines(db, order_id)
    if not lines:
        raise PurchaseOrderEmptyError()
    for so_line_id, add_qty in _payload_qty_by_soline(
            [{"source_sales_order_line_id": ln.source_sales_order_line_id, "qty": ln.qty}
             for ln in lines]).items():
        await assert_within_so_line_quota(db, so_line_id, add_qty, exclude_po_id=po.id)
    return await _transition(db, po, PurchaseOrderStatus.CONFIRMED, AuditAction.CONFIRM,
                             actor_user_id=actor_user_id, actor_user_email=actor_user_email,
                             request=request)


async def cancel_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> PurchaseOrder:
    """→CANCELLED(DRAFT 或 CONFIRMED 皆可取消;释放其占用的 SO 行额度)。
    新守卫(契约 D5):CONFIRMED 有活动入库单({IN_TRANSIT,RECEIVED})不可取消——货已在途/已收,
    订货承诺不可单方作废,须先作废/撤销入库。"""
    po = await get_order_for_update(db, order_id)
    assert_transition(PURCHASE_ORDER_TRANSITIONS, po.status, PurchaseOrderStatus.CANCELLED,
                      PurchaseOrderInvalidTransitionError)
    # 延迟导入避免循环依赖(inbound_order_service 依赖 PO 模型)。
    from app.core.exceptions import PurchaseOrderHasActiveInboundError
    from app.services import inbound_order_service
    if await inbound_order_service.has_active_inbound(db, po.id):
        raise PurchaseOrderHasActiveInboundError()
    return await _transition(db, po, PurchaseOrderStatus.CANCELLED, AuditAction.CANCEL,
                             actor_user_id=actor_user_id, actor_user_email=actor_user_email,
                             request=request)


async def _transition(db: AsyncSession, po: PurchaseOrder, target: str, audit_action: AuditAction,
                      *, actor_user_id, actor_user_email, request: Request | None) -> PurchaseOrder:
    po.status = target
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.PURCHASE_ORDER, action=audit_action,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=po.id, request=request, commit=False)
    await db.commit()
    await db.refresh(po)
    return po


async def delete_order(db: AsyncSession, *, order_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> None:
    """硬删采购单(仅草稿;行 CASCADE)。草稿=从没弄好可删,已确认走取消。"""
    po = await get_order_for_update(db, order_id)
    if po.status not in PURCHASE_ORDER_DELETABLE_STATUSES:
        raise PurchaseOrderNotDraftError()
    await write_audit(db, resource_type=AuditResourceType.PURCHASE_ORDER, action=AuditAction.DELETE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=po.id, request=request, commit=False)
    await db.delete(po)
    await db.commit()


# ---------- 列表 ----------


async def list_orders(db: AsyncSession, *, status=None, supplier_id=None,
                      source_sales_order_id=None, source_sales_order_no=None,
                      page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """采购单列表:筛选(状态/供应商/来源SO id 或单号部分匹配)+ 分页,created_at 降序。
    投影 supplier_display + 来源SO号 + 行数。扁平单据列表(非按 SO 分组)——SO 为中心的视图走
    SO 详情「关联采购单区」;此处来源SO筛选只是在扁平列表内收敛,不破坏排序/分页。"""
    conds = []
    if status:
        conds.append(PurchaseOrder.status == status)
    if supplier_id:
        conds.append(PurchaseOrder.supplier_id == supplier_id)
    if source_sales_order_id:
        conds.append(PurchaseOrder.source_sales_order_id == source_sales_order_id)
    # 来源SO单号部分匹配(用户按 SO 号搜,非内部 id);需 JOIN sales_orders,count 也要带上。
    need_so_join = bool(source_sales_order_no)
    if source_sales_order_no:
        conds.append(SalesOrder.no.ilike(f"%{source_sales_order_no}%"))

    count_stmt = select(func.count(PurchaseOrder.id))
    if need_so_join:
        count_stmt = count_stmt.join(
            SalesOrder, SalesOrder.id == PurchaseOrder.source_sales_order_id)

    line_count = (select(func.count(PurchaseOrderLine.id))
                  .where(PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
                  .scalar_subquery())
    rows, total = await paginate(
        db,
        select(PurchaseOrder, Supplier.name, SalesOrder.no, line_count.label("lc"))
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .join(SalesOrder, SalesOrder.id == PurchaseOrder.source_sales_order_id)
        .where(*conds).order_by(PurchaseOrder.created_at.desc()),
        page=page, size=size, count_stmt=count_stmt.where(*conds), scalars=False)

    items = [{
        "id": o.id, "no": o.no, "source_sales_order_id": o.source_sales_order_id,
        "source_sales_order_no": so_no, "supplier_id": o.supplier_id,
        "supplier_display": sup_name, "status": o.status, "currency": o.currency,
        "total_amount": o.total_amount, "line_count": lc, "created_at": o.created_at,
    } for (o, sup_name, so_no, lc) in rows]
    return items, total


async def list_related_by_sales_order(db: AsyncSession, sales_order_id: int) -> list[dict]:
    """SO 详情「关联采购单区」:该 SO 下所有 PO(含 CANCELLED 并标状态,可追溯)。
    进度计算另按 compute_covered_qty 排除 CANCELLED;此处为可追溯全列。"""
    rows = (await db.execute(
        select(PurchaseOrder, Supplier.name)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .where(PurchaseOrder.source_sales_order_id == sales_order_id)
        .order_by(PurchaseOrder.created_at.desc()))).all()
    return [{
        "id": o.id, "no": o.no, "status": o.status, "supplier_id": o.supplier_id,
        "supplier_display": sup_name, "currency": o.currency, "total_amount": o.total_amount,
    } for (o, sup_name) in rows]


# ---------- 可采行(建单器数据源)----------


async def purchasable_lines(db: AsyncSession, source_sales_order_id: int) -> list[dict]:
    """某 SO 的可采行:每行 required/covered/remaining + 采购建议价(sku.reference_price)。
    建单器唯一数据源,复用 compute_covered_qty。"""
    so = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == source_sales_order_id))).scalar_one_or_none()
    if so is None or so.status != SalesOrderStatus.CONFIRMED:
        raise PurchaseSourceSalesOrderInvalidError(f"源 SO 无效: {source_sales_order_id}")
    so_lines = list((await db.execute(
        select(SalesOrderLine).where(SalesOrderLine.sales_order_id == source_sales_order_id)
        .order_by(SalesOrderLine.sort_order))).scalars().all())
    covered = await compute_covered_qty(db, [ln.id for ln in so_lines])
    ref_prices = {sid: rp for sid, rp in (await db.execute(
        select(Sku.id, Sku.reference_price)
        .where(Sku.id.in_([ln.sku_id for ln in so_lines])))).all()} if so_lines else {}
    out = []
    for ln in so_lines:
        cov = covered.get(ln.id, Decimal("0"))
        remaining = Decimal(str(ln.qty)) - cov
        out.append({
            "source_sales_order_line_id": ln.id, "sku_id": ln.sku_id,
            "name_snapshot": ln.name_snapshot, "spec_text_snapshot": ln.spec_text_snapshot,
            "unit_snapshot": ln.unit_snapshot, "required_qty": float(ln.qty),
            "covered_qty": float(cov), "remaining_qty": float(remaining),
            "default_unit_price": (float(ref_prices[ln.sku_id])
                                   if ref_prices.get(ln.sku_id) is not None else None),
        })
    return out
