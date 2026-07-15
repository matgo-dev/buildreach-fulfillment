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
from app.core.exceptions import NotFoundError, QuotationCannotConvertError
from app.db.models.customer import Customer
from app.db.models.quotation import QuotationStatus
from app.db.models.sales_order import SalesOrder, SalesOrderLine, SalesOrderStatus
from app.db.models.user import User
from app.services import quotation_service
from app.services.numbering import allocate


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
    - UNIQUE(source_quotation_id) / UNIQUE(source_quotation_line_id) DB 层兜底并发漏网。
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
    """反查报价 → 销售单(报价不加前向列,靠此反查)。返回 {id, no} 或 None。
    路径由 UNIQUE(source_quotation_id) 索引支撑;至多一行(整单 1:1)。"""
    row = (await db.execute(
        select(SalesOrder.id, SalesOrder.no)
        .where(SalesOrder.source_quotation_id == quotation_id))).first()
    return {"id": row.id, "no": row.no} if row else None


async def get_order(db: AsyncSession, order_id: int) -> SalesOrder:
    so = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == order_id))).scalar_one_or_none()
    if so is None:
        raise NotFoundError(f"销售单不存在: {order_id}")
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
                      purchase_progress=None, sort="created_at", dir="desc",
                      page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """销售单列表:筛选(状态/客户/报价人/采购进度)+ 排序(created_at|total_amount,asc|desc)+ 分页。

    采购进度=派生值(轴2),按是否**用它筛选**分两条路,别让筛选场景的代价压到热路径:
    - **无进度筛选**(默认热路径):进度只是徽标,DB 直接 count+offset/limit 分页,进度**仅对当前页**派生。
    - **有进度筛选**:派生值须先于分页参与,否则踩分页空洞 + total 失真(§2.6)。故物化候选 →
      全量算进度(共用 purchase_order_service 单一口径)→ 过滤 → count → 切片。内部 SO 千级、
      方案B 毫秒级;升级触发点(十万级)→ 方案C 落冗余列,契约不变。
    """
    from app.services import purchase_order_service

    conds = []
    if status:
        conds.append(SalesOrder.status == status)
    if customer_id:
        conds.append(SalesOrder.customer_id == customer_id)
    if salesperson_id:
        conds.append(SalesOrder.salesperson_id == salesperson_id)

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

    # 无进度筛选:DB 分页,进度仅对当前页派生(不全表物化)。
    if not purchase_progress:
        total = (await db.execute(
            select(func.count(SalesOrder.id)).where(*conds))).scalar_one()
        rows = (await db.execute(base.offset((page - 1) * size).limit(size))).all()
        prog = await purchase_order_service.progress_for_sales_orders(
            db, [o.id for (o, *_) in rows])
        return [_item(o, c, s, lc, prog.get(o.id)) for (o, c, s, lc) in rows], total

    # 有进度筛选:物化候选 → 全量算进度 → 过滤 → count → 切片(派生值先于分页)。
    rows = (await db.execute(base)).all()
    prog = await purchase_order_service.progress_for_sales_orders(db, [o.id for (o, *_) in rows])
    items = [_item(o, c, s, lc, prog.get(o.id)) for (o, c, s, lc) in rows
             if prog.get(o.id) == purchase_progress]
    total = len(items)
    start = (page - 1) * size
    return items[start:start + size], total
