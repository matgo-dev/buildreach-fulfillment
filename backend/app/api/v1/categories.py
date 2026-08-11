"""分类路由 /api/v1/categories。分类树维护 + 规格模板建议。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.category import (
    CategoryCreateIn,
    CategoryOut,
    CategorySpecAttributeIn,
    CategorySpecAttributeOut,
    CategoryUpdateIn,
)
from app.services import category_service, spec_template_service

router = APIRouter(prefix="/categories", tags=["categories"])

_READ = Depends(require_permission(Permissions.PRODUCT_READ))
_MANAGE = Depends(require_permission(Permissions.PRODUCT_MANAGE))


@router.get("/tree", summary="激活分类(扁平,前端组树)")
async def categories_tree(
    include_inactive: bool = Query(False),
    _current: CurrentUser = _READ,
    db: AsyncSession = Depends(get_db),
):
    return success({"items": await category_service.list_tree(
        db, include_inactive=include_inactive)})


@router.post("", summary="新建分类")
async def create_category(body: CategoryCreateIn, request: Request,
                          current: CurrentUser = _MANAGE,
                          db: AsyncSession = Depends(get_db)):
    c = await category_service.create_category(
        db, **body.model_dump(), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(CategoryOut.model_validate(c, from_attributes=True).model_dump())


@router.get("/{code}", summary="分类详情")
async def get_category(code: str, _current: CurrentUser = _READ,
                       db: AsyncSession = Depends(get_db)):
    c = await category_service.get_category(db, code)
    return success(CategoryOut.model_validate(c, from_attributes=True).model_dump())


@router.put("/{code}", summary="编辑分类")
async def update_category(code: str, body: CategoryUpdateIn, request: Request,
                          current: CurrentUser = _MANAGE,
                          db: AsyncSession = Depends(get_db)):
    c = await category_service.update_category(
        db, code=code, **body.model_dump(), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(CategoryOut.model_validate(c, from_attributes=True).model_dump())


@router.post("/{code}/activate", summary="启用分类(同时启用祖先)")
async def activate_category(code: str, request: Request, current: CurrentUser = _MANAGE,
                            db: AsyncSession = Depends(get_db)):
    c = await category_service.activate_category(
        db, code=code, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(CategoryOut.model_validate(c, from_attributes=True).model_dump())


@router.post("/{code}/deactivate", summary="停用分类(同时停用子树)")
async def deactivate_category(code: str, request: Request, current: CurrentUser = _MANAGE,
                              db: AsyncSession = Depends(get_db)):
    c = await category_service.deactivate_category(
        db, code=code, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(CategoryOut.model_validate(c, from_attributes=True).model_dump())


@router.get("/{code}/spec-attributes", summary="当前分类直属规格属性")
async def list_spec_attributes(
    code: str,
    _current: CurrentUser = _READ,
    db: AsyncSession = Depends(get_db),
):
    await category_service.get_category(db, code)
    return success({"items": await spec_template_service.list_direct_attributes(db, code)})


@router.post("/{code}/spec-attributes", summary="新建当前分类规格属性")
async def create_spec_attribute(
    code: str,
    body: CategorySpecAttributeIn,
    request: Request,
    current: CurrentUser = _MANAGE,
    db: AsyncSession = Depends(get_db),
):
    await category_service.get_category(db, code)
    item = await spec_template_service.create_new_attribute(
        db,
        code,
        label_i18n=body.label_i18n,
        value_type=body.value_type,
        unit=body.unit,
        options=[o.model_dump() for o in body.options] if body.options else None,
        scope=body.scope,
        sort_order=body.sort_order,
    )
    await write_audit(
        db,
        resource_type=AuditResourceType.CATEGORY,
        action=AuditAction.UPDATE,
        user_id=current.id,
        user_email=current.email,
        resource_id=code,
        request=request,
        extra={"spec_attribute": item, "operation": "create"},
        commit=False,
    )
    await db.commit()
    return success(CategorySpecAttributeOut(**item).model_dump())


@router.put("/{code}/spec-attributes/{key}", summary="编辑当前分类规格属性")
async def update_spec_attribute(
    code: str,
    key: str,
    body: CategorySpecAttributeIn,
    request: Request,
    current: CurrentUser = _MANAGE,
    db: AsyncSession = Depends(get_db),
):
    await category_service.get_category(db, code)
    item = await spec_template_service.update_attribute(
        db,
        code,
        key,
        label_i18n=body.label_i18n,
        value_type=body.value_type,
        unit=body.unit,
        options=[o.model_dump() for o in body.options] if body.options else None,
        sort_order=body.sort_order,
        scope=body.scope,
    )
    await write_audit(
        db,
        resource_type=AuditResourceType.CATEGORY,
        action=AuditAction.UPDATE,
        user_id=current.id,
        user_email=current.email,
        resource_id=code,
        request=request,
        extra={"spec_attribute": item, "operation": "update"},
        commit=False,
    )
    await db.commit()
    return success(CategorySpecAttributeOut(**item).model_dump())


@router.delete("/{code}/spec-attributes/{key}", summary="删除当前分类规格属性")
async def delete_spec_attribute(
    code: str,
    key: str,
    request: Request,
    current: CurrentUser = _MANAGE,
    db: AsyncSession = Depends(get_db),
):
    await category_service.get_category(db, code)
    await spec_template_service.delete_attribute(db, code, key)
    await write_audit(
        db,
        resource_type=AuditResourceType.CATEGORY,
        action=AuditAction.UPDATE,
        user_id=current.id,
        user_email=current.email,
        resource_id=code,
        request=request,
        extra={"spec_attribute_key": key, "operation": "delete"},
        commit=False,
    )
    await db.commit()
    return success(None)


@router.get("/{code}/spec-suggestions", summary="分类规格模板建议")
async def spec_suggestions(
    code: str,
    _current: CurrentUser = _READ,
    db: AsyncSession = Depends(get_db),
):
    return success({"items": await spec_template_service.get_suggestions(db, code)})
