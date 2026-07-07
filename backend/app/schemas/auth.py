"""认证相关 schemas。M0 基座:仅登录链路(login/change-password/logout/me),无自助注册。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.security import PASSWORD_RULE_MESSAGE, validate_password_strength


class RegisterOut(BaseModel):
    user_id: int
    email: str | None = None


class LoginIn(BaseModel):
    # identifier:邮箱(含 @) / 用户名。M0 无国别手机号解析,不支持 phone_region。
    identifier: str = Field(..., min_length=3, max_length=255)
    password: str


class TokenOut(BaseModel):
    """登录响应。"""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_new(cls, v: str) -> str:
        if not validate_password_strength(v):
            raise ValueError(PASSWORD_RULE_MESSAGE)
        return v


class MeOut(BaseModel):
    """当前用户资料。M0 无组织/专区概念,只暴露账号自身信息。"""

    id: int
    email: str
    name: str
    must_change_password: bool
    roles: list[str]
    permissions: list[str]
