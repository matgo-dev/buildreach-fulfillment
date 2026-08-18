from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import has_permission, require_permission
from app.schemas.inventory_disposition import (
    InventoryDispositionCreateIn,
    InventoryDispositionLineOut,
    InventoryDispositionOut,
)
from app.services import inventory_disposition_service

router = APIRouter(prefix="/inventory-dispositions", tags=["inventory-dispositions"])

_READ = Depends(require_permission(Permissions.INVENTORY_READ))
_MANAGE = Depends(require_permission(Permissions.PURCHASE_MANAGE))


def _can_see_cost(current: CurrentUser) -> bool:
    return has_permission(current, Permissions.PURCHASE_READ_COST)


async def _detail_payload(db: AsyncSession, order, current: CurrentUser) -> dict:
    can_see_cost = _can_see_cost(current)
    lines = await inventory_disposition_service.list_lines(db, order.id)
    return {
        "order": InventoryDispositionOut.build(order, can_see_cost=can_see_cost),
        "lines": [
            InventoryDispositionLineOut.build(line, can_see_cost=can_see_cost)
            for line in lines
        ],
    }


@router.post("", summary="创建库存处置单")
async def create_inventory_disposition(body: InventoryDispositionCreateIn, request: Request,
                                       current: CurrentUser = _MANAGE,
                                       db: AsyncSession = Depends(get_db)):
    order = await inventory_disposition_service.create_disposition(
        db,
        inbound_order_id=body.inbound_order_id,
        receipt_handling=body.receipt_handling,
        reason=body.reason,
        actor_user_id=current.id,
        actor_user_email=current.email,
        request=request,
    )
    return success(await _detail_payload(db, order, current))


@router.get("/by-inbound/{inbound_order_id}", summary="按入库单查询库存处置单")
async def get_inventory_disposition_by_inbound(inbound_order_id: int,
                                               current: CurrentUser = _READ,
                                               db: AsyncSession = Depends(get_db)):
    order = await inventory_disposition_service.get_by_inbound(db, inbound_order_id)
    if order is None:
        return success(None)
    return success(await _detail_payload(db, order, current))
