"""供应商路由 /api/v1/suppliers。CRUD + 启停(建 PO 需选 ACTIVE)。守 supplier:manage/read。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.models.supplier import SupplierStatus
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.common import Page, PageParams
from app.schemas.supplier import (
    SupplierCreateIn,
    SupplierListItem,
    SupplierOut,
    SupplierUpdateIn,
)
from app.services import supplier_service

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

# 扁平码 manage 不隐含 read,读端点用 any(manage 持有者也能读)。
_READ = Depends(require_any_permission(Permissions.SUPPLIER_READ, Permissions.SUPPLIER_MANAGE))
_MANAGE = Depends(require_permission(Permissions.SUPPLIER_MANAGE))


@router.post("", summary="建供应商")
async def create_supplier(body: SupplierCreateIn, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    s = await supplier_service.create_supplier(
        db, **body.model_dump(), actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(SupplierOut.model_validate(s, from_attributes=True).model_dump())


@router.get("", summary="供应商列表(筛选/分页)")
async def list_suppliers(page_params: PageParams = Depends(),
                         status: str | None = None, q: str | None = None,
                         _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    rows, total = await supplier_service.list_suppliers(
        db, status=status, keyword=q, page=page_params.page, size=page_params.size)
    return success(Page(
        items=[SupplierListItem.model_validate(s, from_attributes=True).model_dump()
               for s in rows],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/{supplier_id}", summary="供应商详情")
async def get_supplier(supplier_id: int, _current: CurrentUser = _READ,
                       db: AsyncSession = Depends(get_db)):
    s = await supplier_service.get_supplier(db, supplier_id)
    return success(SupplierOut.model_validate(s, from_attributes=True).model_dump())


@router.put("/{supplier_id}", summary="编辑供应商")
async def update_supplier(supplier_id: int, body: SupplierUpdateIn, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    s = await supplier_service.update_supplier(
        db, supplier_id=supplier_id, **body.model_dump(), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(SupplierOut.model_validate(s, from_attributes=True).model_dump())


@router.post("/{supplier_id}/activate", summary="启用供应商")
async def activate_supplier(supplier_id: int, request: Request,
                            current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    s = await supplier_service.set_status(
        db, supplier_id=supplier_id, target=SupplierStatus.ACTIVE, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(SupplierOut.model_validate(s, from_attributes=True).model_dump())


@router.post("/{supplier_id}/deactivate", summary="停用供应商")
async def deactivate_supplier(supplier_id: int, request: Request,
                              current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    s = await supplier_service.set_status(
        db, supplier_id=supplier_id, target=SupplierStatus.INACTIVE, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(SupplierOut.model_validate(s, from_attributes=True).model_dump())
