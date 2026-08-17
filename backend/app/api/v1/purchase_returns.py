from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import has_permission, require_permission
from app.schemas.common import Page, PageParams
from app.schemas.purchase_return import (
    APCreditMemoOut,
    ConfirmReturnShipmentIn,
    PurchaseReturnCreateIn,
    PurchaseReturnLineOut,
    PurchaseReturnListItem,
    PurchaseReturnOut,
    PurchaseReturnableLineOut,
    RejectIn,
)
from app.services import purchase_return_service

router = APIRouter(prefix="/purchase-returns", tags=["purchase-returns"])

_READ = Depends(require_permission(Permissions.PURCHASE_READ))
_MANAGE = Depends(require_permission(Permissions.PURCHASE_MANAGE))
_INBOUND_MANAGE = Depends(require_permission(Permissions.INBOUND_MANAGE))


def _can_see_cost(current: CurrentUser) -> bool:
    return has_permission(current, Permissions.PURCHASE_READ_COST)


@router.post("", summary="创建并提交采购退货单")
async def create_purchase_return(body: PurchaseReturnCreateIn, request: Request,
                                 current: CurrentUser = _MANAGE,
                                 db: AsyncSession = Depends(get_db)):
    order = await purchase_return_service.create_purchase_return(
        db,
        inbound_order_id=body.inbound_order_id,
        reason=body.reason,
        lines=[ln.model_dump() for ln in body.lines],
        actor_user_id=current.id,
        actor_user_email=current.email,
        request=request,
    )
    detail = await purchase_return_service.get_detail(db, order.id)
    can_see_cost = _can_see_cost(current)
    return success({
        "order": PurchaseReturnOut.build(detail["order"], can_see_cost=can_see_cost),
        "lines": [
            PurchaseReturnLineOut.build(line, can_see_cost=can_see_cost)
            for line in detail["lines"]
        ],
        "ap_credit_memo": APCreditMemoOut.build(detail["ap_credit_memo"]),
    })


@router.post("/{order_id}/approve", summary="审核通过采购退货单")
async def approve_purchase_return(order_id: int, request: Request,
                                  current: CurrentUser = _MANAGE,
                                  db: AsyncSession = Depends(get_db)):
    order = await purchase_return_service.approve_purchase_return(
        db, order_id=order_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(PurchaseReturnOut.build(order, can_see_cost=_can_see_cost(current)))


@router.post("/{order_id}/reject", summary="驳回采购退货单")
async def reject_purchase_return(order_id: int, body: RejectIn, request: Request,
                                 current: CurrentUser = _MANAGE,
                                 db: AsyncSession = Depends(get_db)):
    order = await purchase_return_service.reject_purchase_return(
        db, order_id=order_id, reject_reason=body.reject_reason,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(PurchaseReturnOut.build(order, can_see_cost=_can_see_cost(current)))


@router.post("/{order_id}/confirm-return-shipment", summary="确认采购退货出库")
async def confirm_return_shipment(order_id: int, body: ConfirmReturnShipmentIn,
                                  request: Request, current: CurrentUser = _INBOUND_MANAGE,
                                  db: AsyncSession = Depends(get_db)):
    order = await purchase_return_service.confirm_return_shipment(
        db, order_id=order_id, return_shipment_reference=body.return_shipment_reference,
        return_note=body.return_note, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    detail = await purchase_return_service.get_detail(db, order.id)
    can_see_cost = _can_see_cost(current)
    return success({
        "order": PurchaseReturnOut.build(detail["order"], can_see_cost=can_see_cost),
        "lines": [
            PurchaseReturnLineOut.build(line, can_see_cost=can_see_cost)
            for line in detail["lines"]
        ],
        "ap_credit_memo": APCreditMemoOut.build(detail["ap_credit_memo"]),
    })


@router.get("", summary="采购退货单列表")
async def list_purchase_returns(page_params: PageParams = Depends(),
                                status: str | None = Query(
                                    None,
                                    pattern=(
                                        r"^(PENDING_APPROVAL|APPROVED|REJECTED|RETURNED|VOIDED)$"
                                    )),
                                inbound_order_id: int | None = None,
                                purchase_order_id: int | None = None,
                                supplier_id: int | None = None,
                                q: str | None = None,
                                current: CurrentUser = _READ,
                                db: AsyncSession = Depends(get_db)):
    items, total = await purchase_return_service.list_orders(
        db, status=status, inbound_order_id=inbound_order_id,
        purchase_order_id=purchase_order_id, supplier_id=supplier_id, q=q,
        page=page_params.page, size=page_params.size)
    can_see_cost = _can_see_cost(current)
    return success(Page(
        items=[PurchaseReturnListItem.build(it, can_see_cost=can_see_cost) for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/returnable-lines", summary="某已入库单的采购退货可退行")
async def returnable_lines(inbound_order_id: int = Query(...),
                           _current: CurrentUser = _MANAGE,
                           db: AsyncSession = Depends(get_db)):
    rows = await purchase_return_service.returnable_lines(db, inbound_order_id)
    return success({
        "items": [PurchaseReturnableLineOut.model_validate(r).model_dump() for r in rows],
    })


@router.get("/{order_id}", summary="采购退货单详情")
async def get_purchase_return(order_id: int, current: CurrentUser = _READ,
                              db: AsyncSession = Depends(get_db)):
    detail = await purchase_return_service.get_detail(db, order_id)
    can_see_cost = _can_see_cost(current)
    return success({
        "order": PurchaseReturnOut.build(detail["order"], can_see_cost=can_see_cost),
        "lines": [
            PurchaseReturnLineOut.build(line, can_see_cost=can_see_cost)
            for line in detail["lines"]
        ],
        "ap_credit_memo": (
            APCreditMemoOut.build(detail["ap_credit_memo"])
            if has_permission(current, Permissions.PAYABLE_READ) else None
        ),
    })
