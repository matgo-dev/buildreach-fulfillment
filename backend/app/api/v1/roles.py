"""角色路由 /api/v1/roles。只读角色 → 权限点矩阵查询,role:manage 守卫
(当前仅 ADMIN 持有;不做角色/权限的增删改 —— 那是另一件未立项的事)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.services import role_service

router = APIRouter(prefix="/roles", tags=["roles"])

_MANAGE = Depends(require_permission(Permissions.ROLE_MANAGE))


@router.get("", summary="角色 → 权限点矩阵(只读)")
async def list_roles(_current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    return success(await role_service.list_roles_with_permissions(db))
