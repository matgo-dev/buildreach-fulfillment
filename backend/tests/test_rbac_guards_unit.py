"""RBAC 守卫单测(纯函数/依赖 checker,无 DB):强制改密门必须对所有权限型依赖生效,
不止 require_permission——require_any_permission 曾漏挂此门(评审发现,读接口用它),
must_change_password=True 的账号能绕过改密拦截直接访问业务读接口。"""
import pytest

from app.core.dependencies import CurrentUser
from app.core.exceptions import PasswordChangeRequiredError, PermissionDeniedError
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission

pytestmark = pytest.mark.asyncio


def _user(*, must_change_password: bool, perms: list[str]) -> CurrentUser:
    return CurrentUser(id=1, email="u@test", name="u", must_change_password=must_change_password,
                       token_version=1, roles=[], permissions=perms)


async def test_require_permission_blocks_must_change_password():
    checker = require_permission(Permissions.OUTBOUND_READ)
    with pytest.raises(PasswordChangeRequiredError):
        await checker(_user(must_change_password=True, perms=[Permissions.OUTBOUND_READ]))


async def test_require_any_permission_blocks_must_change_password():
    """回归:require_any_permission 现在与 require_permission 同门(修复前会漏放行)。"""
    checker = require_any_permission(Permissions.OUTBOUND_READ, Permissions.OUTBOUND_MANAGE)
    with pytest.raises(PasswordChangeRequiredError):
        await checker(_user(must_change_password=True, perms=[Permissions.OUTBOUND_READ]))


async def test_require_any_permission_allows_after_password_changed():
    checker = require_any_permission(Permissions.OUTBOUND_READ, Permissions.OUTBOUND_MANAGE)
    current = await checker(_user(must_change_password=False, perms=[Permissions.OUTBOUND_MANAGE]))
    assert current.permissions == [Permissions.OUTBOUND_MANAGE]


async def test_require_any_permission_denies_without_any_matching_code():
    """无权限先于改密门判定(与 require_permission 判序一致:403 权限拒绝,不是改密提示)。"""
    checker = require_any_permission(Permissions.OUTBOUND_READ, Permissions.OUTBOUND_MANAGE)
    with pytest.raises(PermissionDeniedError):
        await checker(_user(must_change_password=True, perms=[]))
