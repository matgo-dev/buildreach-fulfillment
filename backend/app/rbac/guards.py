"""权限/角色守卫。

用法:
    @router.get("/foo", dependencies=[Depends(require_permission(Permissions.X))])
    或
    current = Depends(require_permission(Permissions.X))
"""
from __future__ import annotations

from typing import Iterable

from fastapi import Depends

from app.core.exceptions import PasswordChangeRequiredError, PermissionDeniedError
from app.core.dependencies import CurrentUser, get_current_user
from app.rbac.constants import Permissions

# 强制改密期间放行的权限码(登录/登出/读自身资料)
_MUST_CHANGE_EXEMPT_CODES: frozenset[str] = frozenset({
    Permissions.AUTH_LOGIN,
    Permissions.AUTH_LOGOUT,
    Permissions.AUTH_ME,
})


def _raise_if_must_change(current: CurrentUser, code: str | None = None) -> None:
    """must_change_password=True 且不在豁免集合 → 403 (40007)。"""
    if not current.must_change_password:
        return
    if code is not None and code in _MUST_CHANGE_EXEMPT_CODES:
        return
    raise PasswordChangeRequiredError()


def has_permission(current: CurrentUser, code: str) -> bool:
    """单点权限谓词:端点体内的条件分支(如响应块门控/字段可见性)用它,
    不散写 `code in current.permissions`;依赖注入式守卫仍走 require_permission。"""
    return code in current.permissions


def require_permission(code: str):
    async def checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if code not in current.permissions:
            raise PermissionDeniedError(f"Permission denied: {code}")
        _raise_if_must_change(current, code)
        return current
    return checker


async def block_if_must_change_password(
    current: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """独立依赖:不经 require_permission 的自助端点用此拦截。"""
    _raise_if_must_change(current)
    return current


def require_any_permission(*perm_codes: str):
    allowed: Iterable[str] = perm_codes

    async def checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not any(code in current.permissions for code in allowed):
            raise PermissionDeniedError("Permission denied")
        # 强制改密期间同样拦(镜像 require_permission);此依赖只用于业务读端点(见各
        # api/v1/*.py 的 _READ),豁免码集合(登录/登出/读自身资料)不会出现在 perm_codes 里,
        # 故不做逐码豁免判定,统一按「持任一业务权限仍须先改密」处理。
        _raise_if_must_change(current)
        return current
    return checker
