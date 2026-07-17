"""客户路由 /api/v1/customers。CRUD + 启停(报价需选 ACTIVE)。守 customer:manage/read。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.models.customer import CustomerStatus
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.common import Page, PageParams
from app.schemas.customer import (
    CustomerCreateIn,
    CustomerListItem,
    CustomerOut,
    CustomerUpdateIn,
)
from app.services import customer_service

router = APIRouter(prefix="/customers", tags=["customers"])

# 扁平码 manage 不隐含 read,读端点用 any(manage 持有者也能读)。
_READ = Depends(require_any_permission(Permissions.CUSTOMER_READ, Permissions.CUSTOMER_MANAGE))
_MANAGE = Depends(require_permission(Permissions.CUSTOMER_MANAGE))


@router.post("", summary="建客户")
async def create_customer(body: CustomerCreateIn, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    c = await customer_service.create_customer(
        db, **body.model_dump(), actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(CustomerOut.model_validate(c, from_attributes=True).model_dump())


@router.get("", summary="客户列表(筛选/分页)")
async def list_customers(page_params: PageParams = Depends(),
                         status: str | None = None, q: str | None = None,
                         _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    rows, total = await customer_service.list_customers(
        db, status=status, keyword=q, page=page_params.page, size=page_params.size)
    return success(Page(
        items=[CustomerListItem.model_validate(c, from_attributes=True).model_dump()
               for c in rows],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/{customer_id}", summary="客户详情")
async def get_customer(customer_id: int, _current: CurrentUser = _READ,
                       db: AsyncSession = Depends(get_db)):
    c = await customer_service.get_customer(db, customer_id)
    return success(CustomerOut.model_validate(c, from_attributes=True).model_dump())


@router.put("/{customer_id}", summary="编辑客户")
async def update_customer(customer_id: int, body: CustomerUpdateIn, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    c = await customer_service.update_customer(
        db, customer_id=customer_id, **body.model_dump(), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(CustomerOut.model_validate(c, from_attributes=True).model_dump())


@router.post("/{customer_id}/activate", summary="启用客户")
async def activate_customer(customer_id: int, request: Request,
                            current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    c = await customer_service.set_status(
        db, customer_id=customer_id, target=CustomerStatus.ACTIVE, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(CustomerOut.model_validate(c, from_attributes=True).model_dump())


@router.post("/{customer_id}/deactivate", summary="停用客户")
async def deactivate_customer(customer_id: int, request: Request,
                              current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    c = await customer_service.set_status(
        db, customer_id=customer_id, target=CustomerStatus.INACTIVE, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(CustomerOut.model_validate(c, from_attributes=True).model_dump())
