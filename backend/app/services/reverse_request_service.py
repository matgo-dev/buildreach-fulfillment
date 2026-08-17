"""逆向申请服务(MVP-1:出库前履约中取消)。

本服务只承载申请事实与审批结论,不自动冲销应付、不扣库存、不回滚原正向单据。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    NotFoundError,
    ReverseRequestDuplicateActiveError,
    ReverseRequestHasActiveOutboundError,
    ReverseRequestInvalidResolutionError,
    ReverseRequestInvalidSourceError,
    ReverseRequestInvalidTransitionError,
    ReverseRequestNotFoundError,
)
from app.core.statemachine import assert_transition
from app.db.models.customer import Customer
from app.db.models.inbound_order import InboundOrder, InboundOrderLine, InboundOrderStatus
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.purchase_order import PurchaseOrder
from app.db.models.reverse_request import (
    REVERSE_REQUEST_TRANSITIONS,
    ReverseGoodsStatus,
    ReverseRequest,
    ReverseRequestLine,
    ReverseRequestStatus,
    ReverseRequestType,
    ReverseSupplierResolution,
)
from app.db.models.sales_order import SalesOrder
from app.db.models.supplier import Supplier
from app.services.numbering import allocate
from app.services.repo import get_or_404, paginate


async def _next_reverse_no(db: AsyncSession) -> str:
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.REVERSE_REQUEST, period)
    return format_code(NumberScope.REVERSE_REQUEST, seq, period)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_request(db: AsyncSession, request_id: int) -> ReverseRequest:
    return await get_or_404(db, ReverseRequest, request_id,
                            error_cls=ReverseRequestNotFoundError,
                            message=f"逆向申请不存在: {request_id}")


async def get_request_for_update(db: AsyncSession, request_id: int) -> ReverseRequest:
    return await get_or_404(db, ReverseRequest, request_id, for_update=True,
                            error_cls=ReverseRequestNotFoundError,
                            message=f"逆向申请不存在: {request_id}")


async def list_lines(db: AsyncSession, request_id: int) -> list[ReverseRequestLine]:
    return list((await db.execute(
        select(ReverseRequestLine)
        .where(ReverseRequestLine.reverse_request_id == request_id)
        .order_by(ReverseRequestLine.id))).scalars().all())


async def resolve_request_parties(db: AsyncSession, req: ReverseRequest) -> dict:
    row = (await db.execute(
        select(SalesOrder.no, Customer.name, PurchaseOrder.no, Supplier.name, InboundOrder.no)
        .join(Customer, Customer.id == SalesOrder.customer_id)
        .join(PurchaseOrder, PurchaseOrder.id == req.purchase_order_id)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .join(InboundOrder, InboundOrder.id == req.inbound_order_id)
        .where(SalesOrder.id == req.sales_order_id))).first()
    if row is None:
        return {}
    so_no, customer, po_no, supplier, inb_no = row
    return {
        "sales_order_no": so_no,
        "customer_display": customer,
        "purchase_order_no": po_no,
        "supplier_display": supplier,
        "inbound_order_no": inb_no,
    }


async def _assert_no_active_outbound(db: AsyncSession, sales_order_id: int) -> None:
    rows = list((await db.execute(
        select(OutboundOrder.id, OutboundOrder.no, OutboundOrder.status)
        .where(OutboundOrder.sales_order_id == sales_order_id,
               OutboundOrder.status != OutboundOrderStatus.CANCELLED)
        .order_by(OutboundOrder.id))).all())
    if rows:
        raise ReverseRequestHasActiveOutboundError(
            data={
                "blocking_documents": [
                    {
                        "type": "outbound_order",
                        "id": row.id,
                        "no": row.no,
                        "status": row.status,
                        "path": f"/outbound/{row.id}",
                    }
                    for row in rows
                ],
            })


async def _source_for_inbound(db: AsyncSession, inbound_order_id: int) -> tuple[InboundOrder, PurchaseOrder]:
    inbound = (await db.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_order_id).with_for_update())
    ).scalar_one_or_none()
    if inbound is None:
        raise NotFoundError(f"入库单不存在: {inbound_order_id}")
    if inbound.status not in {InboundOrderStatus.IN_TRANSIT, InboundOrderStatus.RECEIVED}:
        raise ReverseRequestInvalidSourceError("只能基于在途或已入库的活动入库单创建履约中取消申请")
    po = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == inbound.purchase_order_id)
        .with_for_update())).scalar_one_or_none()
    if po is None:
        raise ReverseRequestInvalidSourceError("入库单来源采购单不存在")
    await _assert_no_active_outbound(db, po.source_sales_order_id)
    return inbound, po


def _goods_status_from_inbound(status: str) -> str:
    if status == InboundOrderStatus.RECEIVED:
        return ReverseGoodsStatus.RECEIVED
    return ReverseGoodsStatus.IN_TRANSIT


async def create_fulfillment_cancel(
    db: AsyncSession, *, inbound_order_id: int, reason: str, actor_user_id: int,
    actor_user_email: str, request: Request | None = None,
) -> ReverseRequest:
    clean_reason = reason.strip()
    if not clean_reason:
        raise ReverseRequestInvalidSourceError("取消原因不能为空")
    inbound, po = await _source_for_inbound(db, inbound_order_id)
    lines = list((await db.execute(
        select(InboundOrderLine)
        .where(InboundOrderLine.inbound_order_id == inbound.id)
        .order_by(InboundOrderLine.sort_order, InboundOrderLine.id))).scalars().all())
    if not lines:
        raise ReverseRequestInvalidSourceError("入库单无明细,不可创建逆向申请")

    req = ReverseRequest(
        no=await _next_reverse_no(db),
        request_type=ReverseRequestType.FULFILLMENT_CANCEL,
        status=ReverseRequestStatus.PENDING_REVIEW,
        sales_order_id=po.source_sales_order_id,
        purchase_order_id=po.id,
        inbound_order_id=inbound.id,
        goods_status=_goods_status_from_inbound(inbound.status),
        reason=clean_reason,
        requested_by=actor_user_id,
    )
    db.add(req)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        if "uq_reverse_requests_inbound_active" in str(e.orig or e):
            raise ReverseRequestDuplicateActiveError()
        raise

    for ln in lines:
        db.add(ReverseRequestLine(
            reverse_request_id=req.id,
            inbound_order_line_id=ln.id,
            purchase_order_line_id=ln.purchase_order_line_id,
            sku_id=ln.sku_id,
            name_snapshot=ln.name_snapshot,
            spec_text_snapshot=ln.spec_text_snapshot,
            unit_snapshot=ln.unit_snapshot,
            qty=ln.qty,
        ))
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.REVERSE_REQUEST,
                      action=AuditAction.CREATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=req.id, request=request,
                      extra={"inbound_order_id": inbound.id}, commit=False)
    await db.commit()
    await db.refresh(req)
    return req


async def approve(
    db: AsyncSession, *, request_id: int, supplier_resolution: str, review_note: str | None,
    actor_user_id: int, actor_user_email: str, request: Request | None = None,
) -> ReverseRequest:
    if supplier_resolution not in set(ReverseSupplierResolution.ALL):
        raise ReverseRequestInvalidResolutionError()
    req = await get_request_for_update(db, request_id)
    assert_transition(REVERSE_REQUEST_TRANSITIONS, req.status, ReverseRequestStatus.APPROVED,
                      ReverseRequestInvalidTransitionError)
    req.status = ReverseRequestStatus.APPROVED
    req.supplier_resolution = supplier_resolution
    req.reviewed_at = _now()
    req.reviewed_by = actor_user_id
    req.review_note = review_note
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.REVERSE_REQUEST,
                      action=AuditAction.APPROVE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=req.id, request=request,
                      extra={"supplier_resolution": supplier_resolution}, commit=False)
    await db.commit()
    await db.refresh(req)
    return req


async def reject(
    db: AsyncSession, *, request_id: int, review_note: str | None, actor_user_id: int,
    actor_user_email: str, request: Request | None = None,
) -> ReverseRequest:
    req = await get_request_for_update(db, request_id)
    assert_transition(REVERSE_REQUEST_TRANSITIONS, req.status, ReverseRequestStatus.REJECTED,
                      ReverseRequestInvalidTransitionError)
    req.status = ReverseRequestStatus.REJECTED
    req.reviewed_at = _now()
    req.reviewed_by = actor_user_id
    req.review_note = review_note
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.REVERSE_REQUEST,
                      action=AuditAction.REJECT, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=req.id, request=request,
                      commit=False)
    await db.commit()
    await db.refresh(req)
    return req


async def complete(
    db: AsyncSession, *, request_id: int, completion_note: str | None, actor_user_id: int,
    actor_user_email: str, request: Request | None = None,
) -> ReverseRequest:
    req = await get_request_for_update(db, request_id)
    assert_transition(REVERSE_REQUEST_TRANSITIONS, req.status, ReverseRequestStatus.COMPLETED,
                      ReverseRequestInvalidTransitionError)
    req.status = ReverseRequestStatus.COMPLETED
    req.completed_at = _now()
    req.completed_by = actor_user_id
    req.completion_note = completion_note
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.REVERSE_REQUEST,
                      action=AuditAction.COMPLETE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=req.id, request=request,
                      commit=False)
    await db.commit()
    await db.refresh(req)
    return req


async def list_requests(
    db: AsyncSession, *, status: str | None = None, sales_order_id: int | None = None,
    inbound_order_id: int | None = None, q: str | None = None, page: int, size: int,
) -> tuple[list[dict], int]:
    conds = []
    if status:
        conds.append(ReverseRequest.status == status)
    if sales_order_id:
        conds.append(ReverseRequest.sales_order_id == sales_order_id)
    if inbound_order_id:
        conds.append(ReverseRequest.inbound_order_id == inbound_order_id)
    if q:
        like = f"%{q}%"
        conds.append(or_(ReverseRequest.no.ilike(like), SalesOrder.no.ilike(like),
                         PurchaseOrder.no.ilike(like), InboundOrder.no.ilike(like)))
    line_agg = (
        select(ReverseRequestLine.reverse_request_id,
               func.count(ReverseRequestLine.id).label("line_count"),
               func.coalesce(func.sum(ReverseRequestLine.qty), 0).label("total_qty"))
        .group_by(ReverseRequestLine.reverse_request_id)
        .subquery()
    )
    stmt = (
        select(ReverseRequest, SalesOrder.no.label("sales_order_no"),
               Customer.name.label("customer_display"),
               PurchaseOrder.no.label("purchase_order_no"),
               Supplier.name.label("supplier_display"),
               InboundOrder.no.label("inbound_order_no"),
               func.coalesce(line_agg.c.line_count, 0).label("line_count"),
               func.coalesce(line_agg.c.total_qty, 0).label("total_qty"))
        .join(SalesOrder, SalesOrder.id == ReverseRequest.sales_order_id)
        .join(Customer, Customer.id == SalesOrder.customer_id)
        .join(PurchaseOrder, PurchaseOrder.id == ReverseRequest.purchase_order_id)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .join(InboundOrder, InboundOrder.id == ReverseRequest.inbound_order_id)
        .join(line_agg, line_agg.c.reverse_request_id == ReverseRequest.id, isouter=True)
        .where(*conds)
        .order_by(ReverseRequest.created_at.desc(), ReverseRequest.id.desc())
    )
    rows, total = await paginate(db, stmt, page=page, size=size, scalars=False)
    out = []
    for row in rows:
        req = row[0]
        out.append({
            "id": req.id,
            "no": req.no,
            "request_type": req.request_type,
            "status": req.status,
            "sales_order_id": req.sales_order_id,
            "purchase_order_id": req.purchase_order_id,
            "inbound_order_id": req.inbound_order_id,
            "sales_order_no": row.sales_order_no,
            "purchase_order_no": row.purchase_order_no,
            "inbound_order_no": row.inbound_order_no,
            "customer_display": row.customer_display,
            "supplier_display": row.supplier_display,
            "goods_status": req.goods_status,
            "supplier_resolution": req.supplier_resolution,
            "line_count": row.line_count,
            "total_qty": float(row.total_qty),
            "created_at": req.created_at,
        })
    return out, total
