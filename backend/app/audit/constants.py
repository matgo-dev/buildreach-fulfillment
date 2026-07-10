"""审计资源类型与操作枚举。"""
from __future__ import annotations

from enum import Enum


class AuditResourceType(str, Enum):
    AUTH = "auth"
    USER = "user"
    ROLE = "role"
    PERMISSION = "permission"
    SYSTEM = "system"
    USER_ROLE = "user_role"
    CUSTOMER = "customer"
    SPU = "spu"
    SKU = "sku"
    QUOTATION = "quotation"


class AuditAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    DISABLE = "DISABLE"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGIN_LOCKED = "LOGIN_LOCKED"
    LOGOUT = "LOGOUT"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    USER_DISABLE = "USER_DISABLE"       # ADMIN 停用账号
    USER_ENABLE = "USER_ENABLE"         # ADMIN 启用账号
    ROLE_ASSIGN = "ROLE_ASSIGN"
