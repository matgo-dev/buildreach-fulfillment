"""入库单路由 /api/v1/inbound-orders。基于 CONFIRMED PO 收货 + 状态机 + 确认生成应付款。

守 inbound:manage(写)/ inbound:read(读)。入库单据零成本列(契约 D3),读投影天然无红线;
详情内嵌 PO 摘要走既有 PurchaseOrderOut.build(can_see_cost=...) 脱敏;payable 块仅持 payable:read
且已入库时组装(整块门控,非字段级)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.models.inbound_order import InboundOrderStatus
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import has_permission, require_any_permission, require_permission
from app.rbac.redaction import can_see_cost
from app.schemas.common import Page, PageParams
from app.schemas.inbound_order import (
    InboundOrderCreateIn,
    InboundOrderLineOut,
    InboundOrderListItem,
    InboundOrderOut,
    InboundOrderReceiveIn,
    InboundOrderUnreceiveIn,
    InboundOrderUpdateIn,
    ReceivableLineOut,
)
from app.schemas.payable import PayableOut
from app.schemas.purchase_order import PurchaseOrderOut
from app.services import inbound_order_service, purchase_order_service, unit_service

router = APIRouter(prefix="/inbound-orders", tags=["inbound-orders"])

_READ = Depends(require_any_permission(Permissions.INBOUND_READ, Permissions.INBOUND_MANAGE))
_MANAGE = Depends(require_permission(Permissions.INBOUND_MANAGE))


async def _detail_payload(db, order, current) -> dict:
    lines = await inbound_order_service.list_lines(db, order.id)
    # PO 摘要块(经既有脱敏工厂;无 read_cost → 成本 null)。
    po = await purchase_order_service.get_order(db, order.purchase_order_id)
    parties = await purchase_order_service.resolve_order_parties(db, po)
    payload = {
        "order": InboundOrderOut.build(order, {
            "purchase_order_no": po.no,
            "supplier_display": parties["supplier_display"],
        }),
        "lines": await unit_service.translate_unit_snapshots(
            db, [InboundOrderLineOut.build(ln) for ln in lines]),
        "purchase_order": PurchaseOrderOut.build(po, parties, can_see_cost=can_see_cost(current)),
    }
    # payable 块:仅持 payable:read 且已入库(有活动 payable)时下发。
    if (has_permission(current, Permissions.PAYABLE_READ)
            and order.status == InboundOrderStatus.RECEIVED):
        payable = await inbound_order_service.get_active_payable(db, order.id)
        if payable is not None:
            payload["payable"] = PayableOut.build(payable)
    return payload


@router.post("", summary="基于 CONFIRMED PO 建入库单(在途)")
async def create_inbound_order(body: InboundOrderCreateIn, request: Request,
                               current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await inbound_order_service.create_order(
        db, purchase_order_id=body.purchase_order_id, carrier_name=body.carrier_name,
        tracking_no=body.tracking_no, shipped_at=body.shipped_at, eta=body.eta,
        remark=body.remark, lines=[ln.model_dump() for ln in body.lines],
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, order, current))


@router.get("", summary="入库单列表(筛选/分页)")
async def list_inbound_orders(page_params: PageParams = Depends(),
                              status: str | None = None, purchase_order_id: int | None = None,
                              supplier_id: int | None = None, keyword: str | None = None,
                              current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await inbound_order_service.list_orders(
        db, status=status, purchase_order_id=purchase_order_id, supplier_id=supplier_id,
        keyword=keyword, page=page_params.page, size=page_params.size)
    return success(Page(
        items=[InboundOrderListItem.model_validate(it).model_dump() for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/receivable-lines", summary="某 CONFIRMED PO 的可收行(建单器数据源)")
async def receivable_lines(purchase_order_id: int = Query(...),
                           _current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    rows = await inbound_order_service.receivable_lines(db, purchase_order_id)
    return success({"items": await unit_service.translate_unit_snapshots(
        db, [ReceivableLineOut.model_validate(r).model_dump() for r in rows])})


@router.get("/{order_id}", summary="取入库单(含行 + PO 摘要 + payable 块)")
async def get_inbound_order(order_id: int, current: CurrentUser = _READ,
                            db: AsyncSession = Depends(get_db)):
    order = await inbound_order_service.get_order(db, order_id)
    return success(await _detail_payload(db, order, current))


@router.put("/{order_id}", summary="编辑在途入库单(整单重写)")
async def update_inbound_order(order_id: int, body: InboundOrderUpdateIn, request: Request,
                               current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await inbound_order_service.save_order(
        db, order_id=order_id, carrier_name=body.carrier_name, tracking_no=body.tracking_no,
        shipped_at=body.shipped_at, eta=body.eta, remark=body.remark,
        lines=[ln.model_dump() for ln in body.lines],
        expected_updated_at=body.expected_updated_at, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, order, current))


@router.post("/{order_id}/receive", summary="确认入库(IN_TRANSIT→RECEIVED,生成应付款)")
async def receive_inbound_order(order_id: int, body: InboundOrderReceiveIn, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await inbound_order_service.receive_order(
        db, order_id=order_id, arrived_at=body.arrived_at, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, order, current))


@router.post("/{order_id}/unreceive", summary="撤销入库(RECEIVED→IN_TRANSIT,作废应付款)")
async def unreceive_inbound_order(order_id: int, body: InboundOrderUnreceiveIn, request: Request,
                                  current: CurrentUser = _MANAGE,
                                  db: AsyncSession = Depends(get_db)):
    order = await inbound_order_service.unreceive_order(
        db, order_id=order_id, void_reason=body.void_reason, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, order, current))


@router.post("/{order_id}/cancel", summary="作废入库单(仅在途)")
async def cancel_inbound_order(order_id: int, request: Request,
                               current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await inbound_order_service.cancel_order(
        db, order_id=order_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(await _detail_payload(db, order, current))
