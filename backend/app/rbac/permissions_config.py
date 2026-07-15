"""角色 → 权限点 分配表(v3 §3 权威清单)。

设计原则:
- 权限点 code 不带 scope 后缀(:own/:all/:org 禁止)
- auth:* 给所有角色(系统底层会话)

M0 裁剪:仅保留 ADMIN 角色(auth base + system:* 5 个权限点)。

# TODO(Q22): 角色-权限关系定义方式 — 当前实现:配置文件 + 启动同步(方案 C)
# TODO(Q25): ADMIN 严格不触业务数据(本配置严格遵守)
"""
from __future__ import annotations

from app.rbac.constants import Permissions

# 所有角色都需要的会话权限(auth:*)
_AUTH_BASE = [
    Permissions.AUTH_LOGIN,
    Permissions.AUTH_LOGOUT,
    Permissions.AUTH_ME,
]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "ADMIN": [
        *_AUTH_BASE,
        # 系统级,严格不触业务(Q25 + RBAC 规范 §4.3 / §8.6 职责分离)
        Permissions.USER_MANAGE,
        Permissions.ROLE_MANAGE,
        Permissions.PERMISSION_MANAGE,
        Permissions.SYSTEM_CONFIG,
        Permissions.SYSTEM_AUDIT,
        # 履约:customer 管理暂由 ADMIN 兼管(客户尚无专职角色);product 只留 read 过渡桥,
        # manage 已拆给 PRODUCT_OPERATOR。quote:manage 已归位到 SALES(Q25 职责分离),ADMIN 不再持有。
        Permissions.CUSTOMER_MANAGE,
        Permissions.PRODUCT_READ,
    ],
    "PRODUCT_OPERATOR": [
        *_AUTH_BASE,
        Permissions.PRODUCT_READ,
        Permissions.PRODUCT_MANAGE,
    ],
    # 销售:报价单全生命周期 + 转销售建单读销售单 + 读客户(选客户)+ 读商品(选料)。
    # 不碰主数据写、不碰系统域。
    "SALES": [
        *_AUTH_BASE,
        Permissions.QUOTE_MANAGE,
        Permissions.SALES_READ,
        Permissions.CUSTOMER_READ,
        Permissions.PRODUCT_READ,
    ],
}
