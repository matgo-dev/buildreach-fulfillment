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

    # ----- 履约:customer / product(spu+sku) / quote -----
    CUSTOMER_MANAGE = "customer:manage"
    CUSTOMER_READ = "customer:read"
    PRODUCT_READ = "product:read"
    PRODUCT_MANAGE = "product:manage"
    QUOTE_MANAGE = "quote:manage"
    SALES_READ = "sales:read"
    SALES_MANAGE = "sales:manage"  # SO 域写权限(取消;将来修订复用)。仅 SALES(Q25:ADMIN 不触业务)

    # ----- 履约:supplier(供应商主数据) / purchase(采购单)-----
    SUPPLIER_MANAGE = "supplier:manage"
    SUPPLIER_READ = "supplier:read"
    PURCHASE_MANAGE = "purchase:manage"
    PURCHASE_READ = "purchase:read"
    # 🔴红线开关:采购价/金额可见;无此权限则后端置 null。独立拆出为入库步预埋轴
    # (入库仓库角色将持 purchase:read 见 PO/供应商/数量,但无 read_cost 不见成本)。
    PURCHASE_READ_COST = "purchase:read_cost"

    # ----- 履约:inbound(入库单)/ payable(应付款)-----
    # 入库单据零成本列(契约 D3),故无 inbound:read_cost 轴。
    INBOUND_MANAGE = "inbound:manage"
    INBOUND_READ = "inbound:read"
    # 🔴红线开关:应付款整域(供应商 + 成本)可见;端点级门控,无此权限则整块不下发。
    PAYABLE_READ = "payable:read"

    # ----- 履约:inventory(库存/订单履约跟踪,纯派生只读)-----
    # 无 manage 轴:库存无写入口(无手工调整/盘点),数字全由单据链派生。零成本/供应商字段 → 非红线。
    INVENTORY_READ = "inventory:read"


# auth:* 是系统底层会话权限,不归任何资源域(供启动同步识别,不进矩阵)
SYSTEM_RESERVED_CODES = frozenset({
    Permissions.AUTH_LOGIN,
    Permissions.AUTH_LOGOUT,
    Permissions.AUTH_ME,
})


class ModuleLabel:
    """资源域 module 分组码(稳定机器码,身份非展示;中文侧边栏标签走前端 i18n 映射)。"""
    SYSTEM = "system"
    AUTH = "auth"
    FULFILLMENT = "fulfillment"


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
    Permissions.CUSTOMER_READ: {"name": "客户查看", "module": ModuleLabel.FULFILLMENT},
    Permissions.PRODUCT_READ: {"name": "商品查看", "module": ModuleLabel.FULFILLMENT},
    Permissions.PRODUCT_MANAGE: {"name": "商品管理", "module": ModuleLabel.FULFILLMENT},
    Permissions.QUOTE_MANAGE: {"name": "报价管理", "module": ModuleLabel.FULFILLMENT},
    Permissions.SALES_READ: {"name": "销售单查看", "module": ModuleLabel.FULFILLMENT},
    Permissions.SALES_MANAGE: {"name": "销售单管理", "module": ModuleLabel.FULFILLMENT},

    Permissions.SUPPLIER_MANAGE: {"name": "供应商管理", "module": ModuleLabel.FULFILLMENT},
    Permissions.SUPPLIER_READ: {"name": "供应商查看", "module": ModuleLabel.FULFILLMENT},
    Permissions.PURCHASE_MANAGE: {"name": "采购管理", "module": ModuleLabel.FULFILLMENT},
    Permissions.PURCHASE_READ: {"name": "采购查看", "module": ModuleLabel.FULFILLMENT},
    Permissions.PURCHASE_READ_COST: {"name": "采购成本查看", "module": ModuleLabel.FULFILLMENT},

    Permissions.INBOUND_MANAGE: {"name": "入库管理", "module": ModuleLabel.FULFILLMENT},
    Permissions.INBOUND_READ: {"name": "入库查看", "module": ModuleLabel.FULFILLMENT},
    Permissions.PAYABLE_READ: {"name": "应付款查看", "module": ModuleLabel.FULFILLMENT},
    Permissions.INVENTORY_READ: {"name": "库存查看", "module": ModuleLabel.FULFILLMENT},
}


ROLE_META: dict[str, dict[str, str]] = {
    "ADMIN": {"name": "系统管理员", "description": "系统级管理员,不触业务数据(Q25)"},
    "PRODUCT_OPERATOR": {"name": "商品运营", "description": "商品 SPU/SKU 增改上下架"},
    "SALES": {"name": "销售", "description": "报价单全生命周期;读客户/商品选料"},
    "PURCHASER": {"name": "采购员", "description": "供应商主数据 + 基于销售单发起采购单(建/确认/取消);见采购成本"},
}
