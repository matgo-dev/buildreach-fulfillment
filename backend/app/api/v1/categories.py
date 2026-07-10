"""分类路由 /api/v1/categories。只读引用:激活分类扁平树 + 规格模板建议。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.models.category import Category
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.services import spec_template_service

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("/tree", summary="激活分类(扁平,前端组树)")
async def categories_tree(
    _current: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Category).where(Category.is_active.is_(True))
        .order_by(Category.level, Category.sort_order)
    )).scalars().all()
    items = [{"code": c.code, "parent_code": c.parent_code, "level": c.level,
              "is_leaf": c.is_leaf, "name_i18n": c.name_i18n, "sort_order": c.sort_order}
             for c in rows]
    return success({"items": items})


@router.get("/{code}/spec-suggestions", summary="分类规格模板建议")
async def spec_suggestions(
    code: str,
    _current: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
    db: AsyncSession = Depends(get_db),
):
    return success({"items": await spec_template_service.get_suggestions(db, code)})
