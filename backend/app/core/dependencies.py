"""FastAPI 依赖:从 JWT 解析当前用户,带 roles + permissions。

M0 基座裁剪:无组织概念(无 BuyerOrg/SupplierOrg),CurrentUser 只带账号自身信息。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AccountDeactivatedError, AccountDisabledError, NotAuthenticatedError
from app.core.security import TokenError, decode_token
from app.db.models.permission import Permission
from app.db.models.role import Role
from app.db.models.role_permission import RolePermission
from app.db.models.user import User, UserStatus
from app.db.models.user_role import UserRole
from app.db.session import get_db

# tokenUrl 仅用于 OpenAPI 文档展示,真实登录走 /api/v1/auth/login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


@dataclass
class CurrentUser:
    id: int
    email: str | None
    name: str
    must_change_password: bool
    token_version: int
    username: str | None = None
    phone: str | None = None
    roles: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)


async def _load_roles_and_permissions(
    db: AsyncSession, user_id: int
) -> tuple[list[str], list[str]]:
    role_rows = await db.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
    )
    role_codes = sorted({r for r in role_rows.scalars().all()})

    if not role_codes:
        return [], []

    perm_rows = await db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .where(Role.code.in_(role_codes))
        .distinct()
    )
    perm_codes = sorted({p for p in perm_rows.scalars().all()})
    return role_codes, perm_codes


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    if not token:
        raise NotAuthenticatedError()
    try:
        payload = decode_token(token, expected_type="access")
    except TokenError:
        raise NotAuthenticatedError("Invalid token")

    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        raise NotAuthenticatedError("Invalid token payload")
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        raise NotAuthenticatedError("Invalid token payload")

    user = await db.get(User, user_id)
    if user is None:
        raise NotAuthenticatedError("User not found")
    if user.status == UserStatus.DISABLED:
        raise AccountDisabledError()
    # DEACTIVATED:token_version +1 后旧 token 已失效,下面 tv 校验会拦截;
    # 此处兜底确保新 token_version 签出前也无法访问
    if user.status == UserStatus.DEACTIVATED:
        raise AccountDeactivatedError()

    # token_version 校验:tv 不匹配 → 旧 token 已被吊销(改密/强制下线)
    if int(payload.get("tv", -1)) != user.token_version:
        raise NotAuthenticatedError("Token revoked")

    role_codes, perm_codes = await _load_roles_and_permissions(db, user.id)

    return CurrentUser(
        id=user.id,
        email=user.email,
        username=user.username,
        name=user.name,
        phone=user.phone,
        must_change_password=user.must_change_password,
        token_version=user.token_version,
        roles=role_codes,
        permissions=perm_codes,
    )
