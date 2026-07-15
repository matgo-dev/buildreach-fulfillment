"""用户路由 /api/v1/users。当前仅报价人选择器(轻量参照数据,非用户主数据管理)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/selectable", summary="报价人选择器(ACTIVE 且持 quote:manage 的 id+name)")
async def selectable_users(
    _current: CurrentUser = Depends(require_permission(Permissions.QUOTE_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    return success(await user_service.list_selectable_salespersons(db))
