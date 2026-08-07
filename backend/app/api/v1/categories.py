"""分类路由 /api/v1/categories。分类树维护 + 规格模板建议。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.category import CategoryCreateIn, CategoryOut, CategoryUpdateIn
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


@router.get("/{code}/spec-suggestions", summary="分类规格模板建议")
async def spec_suggestions(
    code: str,
    _current: CurrentUser = _READ,
    db: AsyncSession = Depends(get_db),
):
    return success({"items": await spec_template_service.get_suggestions(db, code)})
