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
    SALES_ORDER = "sales_order"
    SUPPLIER = "supplier"
    PURCHASE_ORDER = "purchase_order"
    INBOUND_ORDER = "inbound_order"
    PAYABLE = "payable"
    OUTBOUND_ORDER = "outbound_order"
    SHIPMENT_ORDER = "shipment_order"
    SHIPMENT_EVENT = "shipment_event"


class AuditAction(str, Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    DISABLE = "DISABLE"
    # 主数据 ACTIVE/INACTIVE 状态切换(供应商启停;将来客户复用同机制)
    ACTIVATE = "ACTIVATE"
    DEACTIVATE = "DEACTIVATE"
    # 报价状态跃迁(归属走 audit,不上业务列)
    LOCK = "LOCK"
    UNLOCK = "UNLOCK"
    VOID = "VOID"
    CONVERT = "CONVERT"       # 报价 LOCKED→CONVERTED(转销售单)
    UNCONVERT = "UNCONVERT"   # 报价 CONVERTED→LOCKED(SO 取消回退;镜像 UNRECEIVE 命名)
    # 采购单状态跃迁:DRAFT→CONFIRMED(下单)/ →CANCELLED
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"
    # 入库单状态跃迁:IN_TRANSIT→RECEIVED(收货)/ RECEIVED→IN_TRANSIT(撤销入库)。
    # 收货/撤销是独立业务语义,不复用 CONFIRM/CANCEL。
    RECEIVE = "RECEIVE"
    UNRECEIVE = "UNRECEIVE"
    # 出库单状态跃迁:DRAFT→ISSUED(确认出库/扣库存)/ ISSUED→DRAFT(撤销出库)。
    # 出库确认/撤销是独立业务语义,不复用 CONFIRM/CANCEL(镜像 RECEIVE/UNRECEIVE 先例)。
    ISSUE = "ISSUE"
    UNISSUE = "UNISSUE"
    # 柜/发运状态跃迁:OPEN→LOADED(封柜确认)/ LOADED→OPEN(撤封柜)/
    # LOADED→DEPARTED(离港确认)/ DEPARTED→LOADED(撤离港)。船务生命周期独立动词,
    # 不复用 CONFIRM/CANCEL(镜像 ISSUE/UNISSUE 先例)。
    LOAD = "LOAD"
    UNLOAD = "UNLOAD"
    DEPART = "DEPART"
    UNDEPART = "UNDEPART"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGIN_LOCKED = "LOGIN_LOCKED"
    LOGOUT = "LOGOUT"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET = "PASSWORD_RESET"   # ADMIN 代重置(≠自助 PASSWORD_CHANGE)
    USER_DISABLE = "USER_DISABLE"       # ADMIN 停用账号
    USER_ENABLE = "USER_ENABLE"         # ADMIN 启用账号
    ROLE_ASSIGN = "ROLE_ASSIGN"
