"""用户管理 schemas。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import PASSWORD_RULE_MESSAGE, validate_password_strength


class AdminUserCreateIn(BaseModel):
    """super admin 创建 ADMIN 用户。"""

    email: EmailStr
    username: str | None = Field(default=None, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    password: str
    role: Literal["ADMIN"]
    must_change_password: bool = True

    @field_validator("password")
    @classmethod
    def _check(cls, v: str) -> str:
        if not validate_password_strength(v):
            raise ValueError(PASSWORD_RULE_MESSAGE)
        return v


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

    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)


class AdminUserListOut(BaseModel):
    items: list[AdminUserOut]
    total: int
