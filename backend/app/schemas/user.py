"""用户管理 schemas。"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator

from app.core.security import PASSWORD_RULE_MESSAGE, validate_password_strength

# 内部账号邮箱允许 *.local 等保留 TLD(SUPER_ADMIN_EMAIL/全量测试夹具约定的内部域名)。
# pydantic EmailStr 底层 email-validator 对 RFC 6761 特殊用途域名(local/test/...)
# 无论 check_deliverability 与否一律硬拒、无参数可绕过,与本仓内部域名约定不兼容,
# 故此处仅做轻量格式校验(不接可投递性/保留域检查)。
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_password(v: str) -> str:
    if not validate_password_strength(v):
        raise ValueError(PASSWORD_RULE_MESSAGE)
    return v


def _valid_email(v: str) -> str:
    v = v.strip()
    if not _EMAIL_RE.match(v):
        raise ValueError("邮箱格式不正确")
    return v.lower()


def _valid_email_opt(v: str | None) -> str | None:
    return v if v is None else _valid_email(v)


def _none_if_blank(v):
    """mode=before:空串/纯空白归 None —— NULL 不占唯一索引,空串会占
    (uq_users_username/phone 全状态唯一,两个"输入后删光"会互撞)。"""
    if isinstance(v, str) and not v.strip():
        return None
    return v


class AdminUserCreateIn(BaseModel):
    """管理员建内部账号(指派单角色)。role 白名单校验在 service 层
    ALLOWED_INTERNAL_ROLES(单一源头,schema 不复制一份枚举)。"""

    email: str = Field(..., max_length=255)
    username: str | None = Field(default=None, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    password: str
    role: str = Field(..., min_length=1, max_length=50)
    must_change_password: bool = True

    _v_email = field_validator("email")(_valid_email)
    _v_password = field_validator("password")(_valid_password)
    _v_username = field_validator("username", mode="before")(_none_if_blank)


class AdminUserOut(BaseModel):
    id: int
    email: str | None = None
    phone: str | None = None
    username: str | None = None
    name: str
    status: str
    must_change_password: bool
    roles: list[str]


class AdminUserUpdateIn(BaseModel):
    """Admin 编辑用户信息。"""

    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)

    _v_email = field_validator("email")(_valid_email_opt)


class AdminUserResetPasswordIn(BaseModel):
    """管理员重置密码:临时密码(强度同建号),成功后强制首登改密。"""

    password: str

    _v_password = field_validator("password")(_valid_password)


class AdminUserRoleIn(BaseModel):
    """替换用户角色(内部用户恒单角色)。白名单校验在 service 层。"""

    role: str = Field(..., min_length=1, max_length=50)
