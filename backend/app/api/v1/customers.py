"""客户路由 /api/v1/customers。M1 最小档:建 + 列(管理后台推后)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.customer import CustomerCreateIn, CustomerOut
from app.services import customer_service

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("", summary="建客户")
async def create_customer(
    body: CustomerCreateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.CUSTOMER_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    c = await customer_service.create_customer(
        db, **body.model_dump(), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(CustomerOut.model_validate(c, from_attributes=True).model_dump())


@router.get("", summary="客户列表")
async def list_customers(
    _current: CurrentUser = Depends(require_permission(Permissions.CUSTOMER_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    rows = await customer_service.list_customers(db)
    return success([
        CustomerOut.model_validate(c, from_attributes=True).model_dump() for c in rows
    ])
