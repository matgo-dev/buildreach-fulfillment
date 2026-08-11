"""角色权限矩阵 / 自定义只读角色 schemas。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RolePermissionItem(BaseModel):
    code: str
    name: str
    module: str


class RoleOut(BaseModel):
    code: str
    name: str
    description: str | None = None
    is_system: bool
    is_custom_readonly: bool
    permissions: list[RolePermissionItem]


class RoleCustomCreateIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(..., min_length=1)

    @field_validator("code")
    @classmethod
    def _code_upper(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("角色名称不能为空")
        return v.strip()

    @field_validator("description")
    @classmethod
    def _desc_blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


class RoleCustomUpdateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("角色名称不能为空")
        return v.strip()

    @field_validator("description")
    @classmethod
    def _desc_blank_to_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None
