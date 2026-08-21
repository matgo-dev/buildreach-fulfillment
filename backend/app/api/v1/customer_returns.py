from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.customer_return import (
    CustomerReturnCreateIn,
    CustomerReturnDetailOut,
    CustomerReturnLineOut,
    CustomerReturnOut,
)
from app.services import customer_return_service

router = APIRouter(prefix="/customer-returns", tags=["customer-returns"])

_READ = Depends(require_any_permission(Permissions.OUTBOUND_READ, Permissions.SALES_READ))
_MANAGE = Depends(require_permission(Permissions.OUTBOUND_MANAGE))


def _detail_payload(detail: dict) -> dict:
    return CustomerReturnDetailOut(
        order=CustomerReturnOut.build(detail["order"]),
        lines=[CustomerReturnLineOut.build(line) for line in detail["lines"]],
        trace=detail["trace"],
    ).model_dump()


@router.post("", summary="创建客户退货单")
async def create_customer_return(body: CustomerReturnCreateIn, request: Request,
                                 current: CurrentUser = _MANAGE,
                                 db: AsyncSession = Depends(get_db)):
    order = await customer_return_service.create_return(
        db,
        outbound_order_id=body.outbound_order_id,
        reason=body.reason,
        lines=[line.model_dump() for line in body.lines],
        actor_user_id=current.id,
        actor_user_email=current.email,
        request=request,
    )
    return success(_detail_payload(await customer_return_service.get_detail(db, order.id)))


@router.get("/returnable-lines", summary="某出库单的客户可退行")
async def list_customer_returnable_lines(outbound_order_id: int = Query(...),
                                         _current: CurrentUser = _MANAGE,
                                         db: AsyncSession = Depends(get_db)):
    return success({"items": await customer_return_service.returnable_lines(db, outbound_order_id)})


@router.get("/{order_id}", summary="客户退货单详情")
async def get_customer_return(order_id: int, _current: CurrentUser = _READ,
                              db: AsyncSession = Depends(get_db)):
    return success(_detail_payload(await customer_return_service.get_detail(db, order_id)))
