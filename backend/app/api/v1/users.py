"""用户路由 /api/v1/users。内部账号管理(T20)+ 报价人选择器。

管理端点全走 user:manage(ADMIN 独持);/selectable 是轻量参照数据,守 quote:manage。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.user import (
    AdminUserCreateIn,
    AdminUserOut,
    AdminUserResetPasswordIn,
    AdminUserRoleIn,
    AdminUserUpdateIn,
)
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

_MANAGE = Depends(require_permission(Permissions.USER_MANAGE))


def _user_out(user, roles: list[str]) -> dict:
    return AdminUserOut(
        id=user.id, email=user.email, phone=user.phone, username=user.username,
        name=user.name, status=user.status,
        must_change_password=user.must_change_password, roles=roles,
    ).model_dump()


@router.get("/selectable", summary="报价人选择器(ACTIVE 且持 quote:manage 的 id+name)")
async def selectable_users(
    _current: CurrentUser = Depends(require_permission(Permissions.QUOTE_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    return success(await user_service.list_selectable_salespersons(db))


@router.get("", summary="用户列表(筛选/分页)")
async def list_users(q: str | None = None, status: str | None = None,
                     page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                     _current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    items, total = await user_service.list_users(
        db, q=q, status=status, page=page, page_size=size)
    return success({
        "items": [_user_out(u, roles) for u, roles in items],
        "total": total, "page": page, "size": size,
    })


@router.post("", summary="建内部账号(指派单角色)")
async def create_user(body: AdminUserCreateIn, request: Request,
                      current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    u = await user_service.create_internal_user(
        db, email=body.email, username=body.username, name=body.name,
        password=body.password, role=body.role,
        must_change_password=body.must_change_password,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(_user_out(u, [body.role]))


@router.put("/{user_id}", summary="编辑用户基本信息(email/phone/name)")
async def update_user(user_id: int, body: AdminUserUpdateIn, request: Request,
                      current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    u = await user_service.update_user(
        db, target_user_id=user_id, actor_user_id=current.id,
        actor_user_email=current.email, email=body.email, phone=body.phone,
        name=body.name, request=request)
    return success(_user_out(u, await user_service.get_user_roles(db, u.id)))


@router.post("/{user_id}/disable", summary="停用账号(不停自己/super admin/最后 ADMIN)")
async def disable_user(user_id: int, request: Request,
                       current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    u = await user_service.disable_user(
        db, target_user_id=user_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(_user_out(u, await user_service.get_user_roles(db, u.id)))


@router.post("/{user_id}/enable", summary="启用账号")
async def enable_user(user_id: int, request: Request,
                      current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    u = await user_service.enable_user(
        db, target_user_id=user_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(_user_out(u, await user_service.get_user_roles(db, u.id)))


@router.post("/{user_id}/reset-password",
             summary="重置密码(临时密码,强制首登改密,踢掉旧会话)")
async def reset_password(user_id: int, body: AdminUserResetPasswordIn, request: Request,
                         current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    u = await user_service.reset_password(
        db, target_user_id=user_id, new_password=body.password,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(_user_out(u, await user_service.get_user_roles(db, u.id)))
