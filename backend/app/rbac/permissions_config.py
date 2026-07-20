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
        # 履约:customer 管理 ADMIN 与 SALES 共持(SALES=业务主责,ADMIN=兜底);product 只留 read 过渡桥,
        # manage 已拆给 PRODUCT_OPERATOR。quote:manage 已归位到 SALES(Q25 职责分离),ADMIN 不再持有。
        Permissions.CUSTOMER_MANAGE,
        Permissions.CUSTOMER_READ,
        Permissions.PRODUCT_READ,
    ],
    "PRODUCT_OPERATOR": [
        *_AUTH_BASE,
        Permissions.PRODUCT_READ,
        Permissions.PRODUCT_MANAGE,
    ],
    # 销售:报价单全生命周期 + 转销售建单读销售单 + 客户主数据全管(建客户→报价选客户
    # 同人同流,客户表无成本/供应商字段非红线)+ 读商品(选料)。不碰其它主数据写、不碰系统域。
    "SALES": [
        *_AUTH_BASE,
        Permissions.QUOTE_MANAGE,
        Permissions.SALES_READ,
        Permissions.SALES_MANAGE,
        Permissions.CUSTOMER_MANAGE,
        Permissions.CUSTOMER_READ,
        Permissions.PRODUCT_READ,
        # 库存(订单履约跟踪):销售看自家 SO 的到货/可发进度。ADMIN 不授(Q25 职责分离)。
        Permissions.INVENTORY_READ,
        # 出库/发运只读:跟踪自家 SO 发货进度;应收=客户售价侧,SALES 本就可见。
        Permissions.OUTBOUND_READ,
        Permissions.SHIPMENT_READ,
        Permissions.RECEIVABLE_READ,
    ],
    # 采购员:供应商主数据全管 + 基于销售单发起采购单(建/编辑/确认/取消)。
    # sales:read = 浏览 SO 发起采购(SO 只对客售价,非红线);read_cost = 采购员当然看采购价;
    # product:read = 选料溯源。不碰系统域、不碰报价/销售写、不碰其它主数据写。
    # 入库:P0 采购员兼收货登记(货代仓外部不进系统,收货由内部人凭到货通知登记,见契约 D8)+
    # 欠款查看(payable:read);已持 read_cost,无新增泄露面。WAREHOUSE 角色触发式后置。
    "PURCHASER": [
        *_AUTH_BASE,
        Permissions.SUPPLIER_MANAGE,
        Permissions.SUPPLIER_READ,
        Permissions.PURCHASE_MANAGE,
        Permissions.PURCHASE_READ,
        Permissions.PURCHASE_READ_COST,
        Permissions.INBOUND_MANAGE,
        Permissions.INBOUND_READ,
        Permissions.PAYABLE_READ,
        Permissions.SALES_READ,
        Permissions.PRODUCT_READ,
        # 库存(订单履约跟踪):采购看按单到货/可发,判断补采/催货。ADMIN 不授(Q25 职责分离)。
        Permissions.INVENTORY_READ,
    ],
    # 物流仓运:组柜/封柜是仓运动作,不并入 PURCHASER(采购侧)也不并入 SALES(销售侧);
    # 出库/发运/物流/报关四步同一操作者。出库/柜零成本/售价 → 无红线泄露;不持 RECEIVABLE_READ
    # (应收=客户售价,整表门控)。sales:read 浏览 SO 发起出库;inventory:read 看可发;product:read 选料溯源。
    "LOGISTICS": [
        *_AUTH_BASE,
        Permissions.OUTBOUND_READ,
        Permissions.OUTBOUND_MANAGE,
        Permissions.SHIPMENT_READ,
        Permissions.SHIPMENT_MANAGE,
        Permissions.SALES_READ,
        Permissions.INVENTORY_READ,
        Permissions.PRODUCT_READ,
    ],
}
