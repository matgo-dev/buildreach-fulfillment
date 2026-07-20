"""转销售服务:锁档报价 → 销售单(整单 1:1,平移行快照)+ 销售单读投影。

范式(SAP SD / NetSuite):分离文档 + 下游反向 FK。销售单自持一份冻结行(平移报价行快照,
不 live 引用报价),转换后销售单是下游采购/发运/财务的唯一真值源。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.statemachine import assert_transition
from app.core.exceptions import (
    NotFoundError,
    QuotationCannotConvertError,
    SalesOrderHasActiveOutboundError,
    SalesOrderHasActivePurchaseError,
    SalesOrderInvalidTransitionError,
)
from app.db.models.customer import Customer
from app.db.models.quotation import QuotationStatus
from app.db.models.sales_order import (
    SALES_ORDER_TRANSITIONS,
    SalesOrder,
    SalesOrderLine,
    SalesOrderStatus,
)
from app.db.models.user import User
from app.services import quotation_service
from app.services.numbering import allocate
from app.services.repo import get_or_404, paginate


async def _next_so_no(db: AsyncSession) -> str:
    # 单据号:SO{YYYYMM}{期内序号};独立号段(NumberScope.SALES_ORDER),按年月。
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.SALES_ORDER, period)
    return format_code(NumberScope.SALES_ORDER, seq, period)


async def convert_quotation(db: AsyncSession, *, quotation_id: int, actor_user_id: int,
                            actor_user_email: str, request: Request | None = None) -> SalesOrder:
    """LOCKED 报价 → 建销售单(平移行快照)+ 报价 LOCKED→CONVERTED。单事务原子。

    - 悲观锁读报价(get_order_for_update),防并发双转;
    - 精确前置守卫:非 LOCKED → QuotationCannotConvertError(不降级通用非法转移);
    - 平移报价行已冻结快照(不重算,零重组);
    - 审计两行:CREATE/SALES_ORDER(销售单诞生)+ CONVERT/QUOTATION(报价转移);
    - 活动行偏唯一(source_quotation_id)/ 复合 UNIQUE(so_id, source_quotation_line_id)
      DB 层兜底并发漏网;取消后重转 = 新活动行与 CANCELLED 留痕行共存。
    """
    order = await quotation_service.get_order_for_update(db, quotation_id)
    if order.status != QuotationStatus.LOCKED:
        raise QuotationCannotConvertError()
    lines = await quotation_service.list_lines(db, quotation_id)

    so = SalesOrder(
        no=await _next_so_no(db), source_quotation_id=order.id,
        customer_id=order.customer_id, salesperson_id=order.salesperson_id,
        language=order.language, currency=order.currency,
        status=SalesOrderStatus.CONFIRMED, total_amount=order.total_amount,
        summary=order.summary, remark=order.remark, created_by=actor_user_id)
    db.add(so)
    await db.flush()
    for ln in lines:
        db.add(SalesOrderLine(
            sales_order_id=so.id, sku_id=ln.sku_id, source_quotation_line_id=ln.id,
            name_snapshot=ln.name_snapshot, spec_text_snapshot=ln.spec_text_snapshot,
            unit_snapshot=ln.unit_snapshot, unit_price=ln.unit_price, qty=ln.qty,
            line_total=ln.line_total, language=ln.language, sort_order=ln.sort_order,
            remark=ln.remark))
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SALES_ORDER, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=so.id, request=request, commit=False)

    order.status = QuotationStatus.CONVERTED
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.QUOTATION, action=AuditAction.CONVERT,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=order.id, request=request, commit=False)
    await db.commit()
    await db.refresh(so)
    return so


async def find_by_source_quotation(db: AsyncSession, quotation_id: int) -> dict | None:
    """反查报价 → **活动**销售单(排除 CANCELLED:取消+重转后同报价多行,只有活动行是现行单据)。
    返回 {id, no} 或 None。至多一行由活动行偏唯一硬保证。"""
    row = (await db.execute(
        select(SalesOrder.id, SalesOrder.no)
        .where(SalesOrder.source_quotation_id == quotation_id,
               SalesOrder.status != SalesOrderStatus.CANCELLED))).first()
    return {"id": row.id, "no": row.no} if row else None


async def get_order(db: AsyncSession, order_id: int) -> SalesOrder:
    return await get_or_404(db, SalesOrder, order_id,
                            error_cls=NotFoundError, message=f"销售单不存在: {order_id}")


async def get_order_for_update(db: AsyncSession, order_id: int) -> SalesOrder:
    """悲观锁读 SO 头行(状态跃迁竞态守卫;镜像报价/PO/入库同名口径)。"""
    return await get_or_404(db, SalesOrder, order_id, for_update=True,
                            error_cls=NotFoundError, message=f"销售单不存在: {order_id}")


async def cancel_order(db: AsyncSession, *, order_id: int, reason: str | None, actor_user_id: int,
                       actor_user_email: str, request: Request | None = None) -> SalesOrder:
    """整单取消(CONFIRMED→CANCELLED,终态)+ 报价 CONVERTED→LOCKED 回退可重转。单事务原子。

    - 锁序 SO 头 → 报价头(建 PO = SO头→SO行;convert = 仅报价头;无环无死锁,评审 B2 核定);
    - 下游守卫(两条互不替代,分别拦采购/出库两条下游链):
      - 存在非 CANCELLED 的 PO → 41802;
      - 存在非 CANCELLED 的出库单(含 DRAFT 草稿)→ 41803 —— 草稿未扣库存但引用了本 SO 的
        行/价,放行会留下一张指向已取消 SO 的活动出库单(悬空引用,后续确认出库前才会被
        41905 兜底,但草稿态本身已是脏数据,故此处提前拦)。
      不级联砍下游——解链人工自下而上:先取消全部 PO / 出库单再取消 SO。
    - 报价断言 CONVERTED 后回退 LOCKED(断言失败 = 不变式破坏,如实 RuntimeError 500);
    - 审计两行 extra 互指:CANCEL/SO(quotation_id)+ UNCONVERT/报价(sales_order_id)。
    """
    from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
    from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderStatus

    so = await get_order_for_update(db, order_id)
    assert_transition(SALES_ORDER_TRANSITIONS, so.status, SalesOrderStatus.CANCELLED,
                      SalesOrderInvalidTransitionError)
    active_po = (await db.execute(
        select(PurchaseOrder.id).where(
            PurchaseOrder.source_sales_order_id == so.id,
            PurchaseOrder.status != PurchaseOrderStatus.CANCELLED).limit(1))).first()
    if active_po:
        raise SalesOrderHasActivePurchaseError(
            f"存在活动采购单(如 #{active_po[0]}),请先取消全部采购单")
    active_ob = (await db.execute(
        select(OutboundOrder.id).where(
            OutboundOrder.sales_order_id == so.id,
            OutboundOrder.status != OutboundOrderStatus.CANCELLED).limit(1))).first()
    if active_ob:
        raise SalesOrderHasActiveOutboundError(
            f"存在活动出库单(如 #{active_ob[0]}),请先取消/撤销全部出库单")

    so.status = SalesOrderStatus.CANCELLED
    so.cancelled_at = datetime.now(timezone.utc).replace(tzinfo=None)
    so.cancelled_by = actor_user_id
    so.cancel_reason = reason
    await db.flush()

    quotation = await quotation_service.get_order_for_update(db, so.source_quotation_id)
    if quotation.status != QuotationStatus.CONVERTED:
        raise RuntimeError(  # 不变式破坏:活动 SO 的来源报价必为 CONVERTED(评审 N4:如实 500)
            f"invariant broken: quotation {quotation.id} status={quotation.status}, "
            f"expected CONVERTED while cancelling SO {so.id}")
    quotation.status = QuotationStatus.LOCKED
    await db.flush()

    await write_audit(db, resource_type=AuditResourceType.SALES_ORDER, action=AuditAction.CANCEL,
                      user_id=actor_user_id, user_email=actor_user_email, resource_id=so.id,
                      request=request, extra={"quotation_id": quotation.id}, commit=False)
    await write_audit(db, resource_type=AuditResourceType.QUOTATION, action=AuditAction.UNCONVERT,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=quotation.id, request=request,
                      extra={"sales_order_id": so.id}, commit=False)
    await db.commit()
    await db.refresh(so)
    return so


async def list_lines(db: AsyncSession, order_id: int) -> list[SalesOrderLine]:
    return list((await db.execute(
        select(SalesOrderLine).where(SalesOrderLine.sales_order_id == order_id)
        .order_by(SalesOrderLine.sort_order))).scalars().all())


async def resolve_order_parties(db: AsyncSession, so: SalesOrder) -> dict:
    """详情投影:客户 / 报价人展示名 + 来源报价号(反查展示)。口径同报价 resolve_order_parties。"""
    cust = (await db.execute(
        select(Customer.name).where(Customer.id == so.customer_id))).scalar_one_or_none()
    sp = (await db.execute(
        select(User.name).where(User.id == so.salesperson_id))).scalar_one_or_none()
    from app.db.models.quotation import QuotationOrder
    src_no = (await db.execute(
        select(QuotationOrder.no).where(
            QuotationOrder.id == so.source_quotation_id))).scalar_one_or_none()
    return {
        "customer_display": cust or f"#{so.customer_id}",
        "salesperson_display": sp or f"#{so.salesperson_id}",
        "source_quotation_no": src_no,
    }


async def list_orders(db: AsyncSession, *, status=None, customer_id=None, salesperson_id=None,
                      no=None, purchase_progress=None, purchasable_only=False,
                      sort="created_at", dir="desc",
                      page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """销售单列表:筛选(状态/客户/报价人/采购进度)+ 排序(created_at|total_amount,asc|desc)+ 分页。

    采购进度=派生值(轴2),按是否**按它筛选**分两条路,别让筛选场景的代价压到热路径:
    - **无进度筛选**(默认热路径):进度只是徽标,DB 直接 count+offset/limit 分页,进度**仅对当前页**派生。
    - **按进度筛选**(purchase_progress 指定单态,或 purchasable_only 排除已采完):派生值须先于分页参与,
      否则踩分页空洞 + total 失真(§2.6)。故物化候选 → 全量算进度(共用 purchase_order_service 单一
      口径)→ 过滤 → count → 切片。内部 SO 千级、方案B 毫秒级;升级触发点(十万级)→ 方案C 落冗余列。

    purchasable_only:采购台选单入口用——只列**可发起采购**的 SO(排除 FULLY_ORDERED);
    与 purchase_progress 并存时以 purchase_progress(更具体)为准。
    """
    from app.db.models.purchase_order import PurchaseProgress
    from app.services import purchase_order_service

    conds = []
    if status:
        conds.append(SalesOrder.status == status)
    if customer_id:
        conds.append(SalesOrder.customer_id == customer_id)
    if salesperson_id:
        conds.append(SalesOrder.salesperson_id == salesperson_id)
    if no:
        # 销售单号模糊搜(采购台选单入口按 SO 号找),镜像采购单列表 source_sales_order_no。
        conds.append(SalesOrder.no.ilike(f"%{no}%"))
    if purchasable_only:
        # 「可发起采购」语义自含「须 CONFIRMED」(评审 S3):CANCELLED 单全 PO 已取消,
        # 进度会回 NOT_ORDERED,不加此条会被当成候选——服务端收紧,不靠调用方传 status。
        conds.append(SalesOrder.status == SalesOrderStatus.CONFIRMED)

    line_count = (select(func.count(SalesOrderLine.id))
                  .where(SalesOrderLine.sales_order_id == SalesOrder.id)
                  .scalar_subquery())
    sort_field = SalesOrder.total_amount if sort == "total_amount" else SalesOrder.created_at
    order_col = sort_field.asc() if dir == "asc" else sort_field.desc()
    base = (select(SalesOrder, Customer.name, User.name, line_count.label("lc"))
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .join(User, User.id == SalesOrder.salesperson_id)
            .where(*conds).order_by(order_col))

    def _item(o, cust_name, sp_name, lc, progress):
        return {
            "id": o.id, "no": o.no, "summary": o.summary,
            "customer_display": cust_name, "salesperson_display": sp_name,
            "status": o.status, "currency": o.currency, "total_amount": o.total_amount,
            "line_count": lc, "created_at": o.created_at, "purchase_progress": progress,
        }

    # 无派生筛选:DB 分页,进度仅对当前页派生(不全表物化)。
    if not purchase_progress and not purchasable_only:
        rows, total = await paginate(
            db, base, page=page, size=size,
            count_stmt=select(func.count(SalesOrder.id)).where(*conds), scalars=False)
        prog = await purchase_order_service.progress_for_sales_orders(
            db, [o.id for (o, *_) in rows])
        return [_item(o, c, s, lc, prog.get(o.id)) for (o, c, s, lc) in rows], total

    # 按进度筛选:物化候选 → 全量算进度 → 过滤 → count → 切片(派生值先于分页)。
    rows = (await db.execute(base)).all()
    prog = await purchase_order_service.progress_for_sales_orders(db, [o.id for (o, *_) in rows])

    def _keep(pid) -> bool:
        p = prog.get(pid)
        if purchase_progress:  # 指定单态优先(更具体)
            return p == purchase_progress
        return p != PurchaseProgress.FULLY_ORDERED  # purchasable_only:排除已采完

    items = [_item(o, c, s, lc, prog.get(o.id)) for (o, c, s, lc) in rows if _keep(o.id)]
    total = len(items)
    start = (page - 1) * size
    return items[start:start + size], total
