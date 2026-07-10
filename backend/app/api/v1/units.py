"""单位路由 /api/v1/units。只读引用:激活售卖单位列表,供 SKU 创建下拉。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.models.unit import Unit
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission

router = APIRouter(prefix="/units", tags=["units"])


@router.get("", summary="激活售卖单位列表(供 SKU 创建下拉)")
async def list_units(
    _current: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        select(Unit).where(Unit.is_active.is_(True)).order_by(Unit.sort_order, Unit.code)
    )).scalars().all()
    items = [{"code": u.code, "label_i18n": u.label_i18n, "sort_order": u.sort_order}
             for u in rows]
    return success({"items": items})
