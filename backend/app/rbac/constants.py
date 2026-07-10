"""权限点常量。

设计原则(v3 §0.3):
- 权限点回答"能不能做某个动作",**不带 scope 后缀**(禁止 `:own` / `:all` / `:org`)
- 数据范围由 scope_config.py 单独管理
- auth:* 是系统底层会话权限,不在业务矩阵内,但仍参与启动同步

M0 裁剪:仅保留 auth:* + system:* 两组(履约系统基座,无业务权限点)。
"""
from __future__ import annotations


class Permissions:
    """所有权限点。v3 标准:`<resource>:<action>`,不带 scope 后缀。"""

    # ----- 系统底层会话(独立于业务矩阵)-----
    AUTH_LOGIN = "auth:login"
    AUTH_LOGOUT = "auth:logout"
    AUTH_ME = "auth:me"

    # ----- 系统:user / role / permission / system -----
    USER_MANAGE = "user:manage"
    ROLE_MANAGE = "role:manage"
    PERMISSION_MANAGE = "permission:manage"
    SYSTEM_CONFIG = "system:config"
    SYSTEM_AUDIT = "system:audit"

    # ----- 履约:customer / catalog(spu+sku) / quote -----
    CUSTOMER_MANAGE = "customer:manage"
    CATALOG_READ = "catalog:read"
    CATALOG_MANAGE = "catalog:manage"
    QUOTE_MANAGE = "quote:manage"


# auth:* 是系统底层会话权限,不归任何资源域(供启动同步识别,不进矩阵)
SYSTEM_RESERVED_CODES = frozenset({
    Permissions.AUTH_LOGIN,
    Permissions.AUTH_LOGOUT,
    Permissions.AUTH_ME,
})


class ModuleLabel:
    """资源域 module 标签(用于侧边栏分组)。"""
    SYSTEM = "系统"
    AUTH = "auth"
    FULFILLMENT = "履约"


# 权限点元数据(用于启动同步:name / module)
PERMISSION_META: dict[str, dict[str, str]] = {
    Permissions.AUTH_LOGIN: {"name": "登录", "module": ModuleLabel.AUTH},
    Permissions.AUTH_LOGOUT: {"name": "登出", "module": ModuleLabel.AUTH},
    Permissions.AUTH_ME: {"name": "获取当前用户", "module": ModuleLabel.AUTH},

    Permissions.USER_MANAGE: {"name": "用户管理", "module": ModuleLabel.SYSTEM},
    Permissions.ROLE_MANAGE: {"name": "角色管理", "module": ModuleLabel.SYSTEM},
    Permissions.PERMISSION_MANAGE: {"name": "权限管理", "module": ModuleLabel.SYSTEM},
    Permissions.SYSTEM_CONFIG: {"name": "系统配置", "module": ModuleLabel.SYSTEM},
    Permissions.SYSTEM_AUDIT: {"name": "审计日志", "module": ModuleLabel.SYSTEM},

    Permissions.CUSTOMER_MANAGE: {"name": "客户管理", "module": ModuleLabel.FULFILLMENT},
    Permissions.CATALOG_READ: {"name": "商品目录查看", "module": ModuleLabel.FULFILLMENT},
    Permissions.CATALOG_MANAGE: {"name": "商品目录管理", "module": ModuleLabel.FULFILLMENT},
    Permissions.QUOTE_MANAGE: {"name": "报价管理", "module": ModuleLabel.FULFILLMENT},
}


ROLE_META: dict[str, dict[str, str]] = {
    "ADMIN": {"name": "系统管理员", "description": "系统级管理员,不触业务数据(Q25)"},
    "CATALOG_OPERATOR": {"name": "商品运营", "description": "商品目录 SPU/SKU 增改上下架"},
}
