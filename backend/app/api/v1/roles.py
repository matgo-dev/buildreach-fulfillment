"""角色路由 /api/v1/roles。

系统内置角色只读展示;自定义角色仅允许配置只读权限,用于外部/审阅类账号。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.role import RoleCustomCreateIn, RoleCustomUpdateIn
from app.services import role_service

router = APIRouter(prefix="/roles", tags=["roles"])

_MANAGE = Depends(require_permission(Permissions.ROLE_MANAGE))


@router.get("", summary="角色 → 权限点矩阵")
async def list_roles(_current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    return success(await role_service.list_roles_with_permissions(db))


@router.get("/assignable-permissions", summary="自定义只读角色可选权限点")
async def list_assignable_permissions(
    _current: CurrentUser = _MANAGE,
    db: AsyncSession = Depends(get_db),
):
    return success(await role_service.list_assignable_permissions(db))


@router.post("", summary="创建自定义只读角色")
async def create_role(body: RoleCustomCreateIn, request: Request,
                      current: CurrentUser = _MANAGE,
                      db: AsyncSession = Depends(get_db)):
    return success(await role_service.create_custom_role(
        db, code=body.code, name=body.name, description=body.description,
        permission_codes=body.permissions,
        actor_user_id=current.id, actor_user_email=current.email, request=request))


@router.put("/{code}", summary="更新自定义只读角色")
async def update_role(code: str, body: RoleCustomUpdateIn, request: Request,
                      current: CurrentUser = _MANAGE,
                      db: AsyncSession = Depends(get_db)):
    return success(await role_service.update_custom_role(
        db, code=code, name=body.name, description=body.description,
        permission_codes=body.permissions,
        actor_user_id=current.id, actor_user_email=current.email, request=request))


@router.delete("/{code}", summary="删除未分配的自定义角色")
async def delete_role(code: str, request: Request, current: CurrentUser = _MANAGE,
                      db: AsyncSession = Depends(get_db)):
    await role_service.delete_custom_role(
        db, code=code, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success()
