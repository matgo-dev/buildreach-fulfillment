"""转销售服务:锁档报价 → 销售单(整单 1:1,平移行快照)+ 销售单读投影。

范式(SAP SD / NetSuite):分离文档 + 下游反向 FK。销售单自持一份冻结行(平移报价行快照,
不 live 引用报价),转换后销售单是下游采购/发运/财务的唯一真值源。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import case, func, select, true
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
    active_pos = list((await db.execute(
        select(PurchaseOrder.id, PurchaseOrder.no, PurchaseOrder.status).where(
            PurchaseOrder.source_sales_order_id == so.id,
            PurchaseOrder.status != PurchaseOrderStatus.CANCELLED)
        .order_by(PurchaseOrder.id))).all())
    if active_pos:
        raise SalesOrderHasActivePurchaseError(
            "存在活动采购单,请先取消全部采购单",
            data={
                "blocking_kind": "purchase_order",
                "next_action": "请先取消全部采购单",
                "blocking_documents": [
                    {
                        "type": "purchase_order",
                        "id": row.id,
                        "no": row.no,
                        "status": row.status,
                        "path": f"/purchasing/orders/{row.id}",
                    }
                    for row in active_pos
                ],
            },
        )
    active_obs = list((await db.execute(
        select(OutboundOrder.id, OutboundOrder.no, OutboundOrder.status).where(
            OutboundOrder.sales_order_id == so.id,
            OutboundOrder.status != OutboundOrderStatus.CANCELLED)
        .order_by(OutboundOrder.id))).all())
    if active_obs:
        raise SalesOrderHasActiveOutboundError(
            "存在活动出库单,请先取消草稿出库单;已出库单不可回退原流程",
            data={
                "blocking_kind": "outbound_order",
                "next_action": "请先取消草稿出库单;已出库单不可取消,出库后异常请联系管理员处理",
                "blocking_documents": [
                    {
                        "type": "outbound_order",
                        "id": row.id,
                        "no": row.no,
                        "status": row.status,
                        "path": f"/outbound/{row.id}",
                    }
                    for row in active_obs
                ],
            },
        )

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


async def _progress_for_page(db: AsyncSession, so_ids: list[int]) -> dict[int, str]:
    """仅对当页 SO 从 **covered_qty 列**派生进度徽标(有界:page ids 一次聚合)。
    走 classify_progress 唯一判据内核 —— 与筛选路径 SQL case 同源。零行 SO → NOT_ORDERED。"""
    from collections import defaultdict

    from app.services.purchase_order_service import classify_progress
    if not so_ids:
        return {}
    rows = (await db.execute(
        select(SalesOrderLine.sales_order_id, SalesOrderLine.covered_qty, SalesOrderLine.qty)
        .where(SalesOrderLine.sales_order_id.in_(so_ids)))).all()
    agg: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])  # [total, fully, anyc]
    for soid, cov, q in rows:
        a = agg[soid]
        a[0] += 1
        if cov >= q:
            a[1] += 1
        if cov > 0:
            a[2] += 1
    return {soid: classify_progress(*agg.get(soid, (0, 0, 0))) for soid in so_ids}


def _progress_case(prog_agg):
    """列表筛选路径的 SQL 进度表达式,镜像 classify_progress(total,fully,anyc) 同序判据。
    prog_agg = 关联到 SalesOrder 的 LATERAL 聚合(总是返回一行,零行 SO → total=0)。"""
    from app.db.models.purchase_order import PurchaseProgress
    return case(
        (func.coalesce(prog_agg.c.total, 0) == 0, PurchaseProgress.NOT_ORDERED),
        (prog_agg.c.fully == prog_agg.c.total, PurchaseProgress.FULLY_ORDERED),
        (prog_agg.c.anyc > 0, PurchaseProgress.PARTIALLY_ORDERED),
        else_=PurchaseProgress.NOT_ORDERED,
    )


async def list_orders(db: AsyncSession, *, status=None, customer_id=None, salesperson_id=None,
                      no=None, purchase_progress=None, purchasable_only=False,
                      sort="created_at", dir="desc",
                      page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """销售单列表:筛选(状态/客户/报价人/采购进度)+ 排序(created_at|total_amount,asc|desc)+ 分页。

    采购进度=派生值(轴2),徽标两条分支均从 sales_order_lines.covered_qty **物化列**派生(方案C),
    按是否**按它筛选**分两条路,别让筛选代价压到热路径:
    - **无进度筛选**(默认热路径):先 count+offset/limit 分页,再**仅对当页** SO 从 covered_qty 列派生徽标
      (有界,不对全表/全候选聚合)。
    - **按进度筛选**(purchase_progress 指定单态,或 purchasable_only 排除已采完):派生值须先于分页参与
      (否则踩分页空洞 + total 失真)。用 `LEFT JOIN LATERAL` 相关子查询按候选 SO 逐行走
      ix_sales_order_lines_sales_order_id 索引聚合,进度 case 谓词下推 WHERE → 真·count+offset/limit
      分页。covered_qty 落列前此处曾把全部候选行读进内存 Python 算,是增长型性能雷。

    purchasable_only:采购台选单入口用——只列**可发起采购**的 SO(排除 FULLY_ORDERED);
    与 purchase_progress 并存时以 purchase_progress(更具体)为准。
    """
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

    def _item(o, cust_name, sp_name, lc, progress):
        return {
            "id": o.id, "no": o.no, "summary": o.summary,
            "customer_display": cust_name, "salesperson_display": sp_name,
            "status": o.status, "currency": o.currency, "total_amount": o.total_amount,
            "line_count": lc, "created_at": o.created_at, "purchase_progress": progress,
        }

    # 无进度筛选(热路径):先分页,再仅对当页 SO 从 covered_qty 列派生徽标(有界)。
    if not purchase_progress and not purchasable_only:
        base = (select(SalesOrder, Customer.name, User.name, line_count.label("lc"))
                .join(Customer, Customer.id == SalesOrder.customer_id)
                .join(User, User.id == SalesOrder.salesperson_id)
                .where(*conds).order_by(order_col))
        rows, total = await paginate(
            db, base, page=page, size=size,
            count_stmt=select(func.count(SalesOrder.id)).where(*conds), scalars=False)
        prog = await _progress_for_page(db, [o.id for (o, *_) in rows])
        return [_item(o, c, s, lc, prog.get(o.id)) for (o, c, s, lc) in rows], total

    # 有进度筛选(选单抽屉等):LATERAL 相关聚合 + case 谓词下推 → 真分页。
    prog_agg = (
        select(
            func.count(SalesOrderLine.id).label("total"),
            func.count().filter(SalesOrderLine.covered_qty >= SalesOrderLine.qty).label("fully"),
            func.count().filter(SalesOrderLine.covered_qty > 0).label("anyc"),
        )
        .where(SalesOrderLine.sales_order_id == SalesOrder.id)
        .correlate(SalesOrder).lateral("prog"))
    progress_expr = _progress_case(prog_agg)
    if purchase_progress:  # 指定单态优先(更具体)
        conds.append(progress_expr == purchase_progress)
    else:  # purchasable_only:排除已采完
        from app.db.models.purchase_order import PurchaseProgress
        conds.append(progress_expr != PurchaseProgress.FULLY_ORDERED)

    base = (select(SalesOrder, Customer.name, User.name, line_count.label("lc"),
                   progress_expr.label("prog"))
            .join(Customer, Customer.id == SalesOrder.customer_id)
            .join(User, User.id == SalesOrder.salesperson_id)
            .outerjoin(prog_agg, true())
            .where(*conds).order_by(order_col))
    count_stmt = (select(func.count(SalesOrder.id))
                  .outerjoin(prog_agg, true()).where(*conds))
    rows, total = await paginate(db, base, page=page, size=size,
                                 count_stmt=count_stmt, scalars=False)
    return [_item(o, c, s, lc, prog) for (o, c, s, lc, prog) in rows], total
