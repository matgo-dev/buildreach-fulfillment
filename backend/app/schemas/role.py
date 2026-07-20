"""角色权限矩阵 schemas(只读)。"""
from __future__ import annotations

from pydantic import BaseModel


class RolePermissionItem(BaseModel):
    code: str
    name: str
    module: str


class RoleOut(BaseModel):
    code: str
    name: str
    description: str | None = None
    permissions: list[RolePermissionItem]
