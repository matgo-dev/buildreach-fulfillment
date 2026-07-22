/**
 * 单一可信源:整个前端的权限相关展示/校验/过滤都从这里读。
 *
 * 与后端 app/rbac/constants.py 等价。后端是权威,前端是 UX 友好层 —
 * 任何冲突以后端为准。
 *
 * 与后端 app/rbac/constants.py 等价。业务域:商品(PRODUCT_OPERATOR)、报价/客户(SALES)、
 * 供应商/采购(PURCHASER)、出库/发运(LOGISTICS);ADMIN 纯系统域,不持任何业务权限点(Q25 职责分离)。
 */

import type { RoleCode } from "@/lib/auth";

export const Permissions = {
  // ----- 系统底层会话(独立于业务矩阵)-----
  AUTH_LOGIN: "auth:login",
  AUTH_LOGOUT: "auth:logout",
  AUTH_ME: "auth:me",

  // ----- 系统:user / role / permission / system -----
  USER_MANAGE: "user:manage",
  ROLE_MANAGE: "role:manage",
  PERMISSION_MANAGE: "permission:manage",
  SYSTEM_CONFIG: "system:config",
  SYSTEM_AUDIT: "system:audit",

  // ----- 履约:客户 / 商品(SPU+SKU)/ 报价 -----
  CUSTOMER_MANAGE: "customer:manage",
  CUSTOMER_READ: "customer:read",
  PRODUCT_READ: "product:read",
  PRODUCT_MANAGE: "product:manage",
  QUOTE_MANAGE: "quote:manage",
  SALES_READ: "sales:read",
  SALES_MANAGE: "sales:manage",

  // ----- 采购:供应商 / 采购单 -----
  SUPPLIER_READ: "supplier:read",
  SUPPLIER_MANAGE: "supplier:manage",
  PURCHASE_READ: "purchase:read",
  PURCHASE_MANAGE: "purchase:manage",
  // 红线:采购价 / 采购金额可见门(后端脱敏为 null,前端仅决定是否显示成本列语义)。
  PURCHASE_READ_COST: "purchase:read_cost",

  // ----- 履约:入库单 / 应付款 -----
  // 入库单据零成本列(契约 D3),故无 inbound:read_cost 轴。
  INBOUND_READ: "inbound:read",
  INBOUND_MANAGE: "inbound:manage",
  // 红线域:应付款整域只对持 payable:read 者下发(后端整块门控,非字段级)。
  PAYABLE_READ: "payable:read",

  // ----- 履约:库存(订单履约跟踪,纯派生,无 manage 轴)-----
  INVENTORY_READ: "inventory:read",

  // ----- 履约:出库单 / 发运柜(出库单据零售价/零成本,故无 read_cost 轴)-----
  OUTBOUND_READ: "outbound:read",
  OUTBOUND_MANAGE: "outbound:manage",
  SHIPMENT_READ: "shipment:read",
  SHIPMENT_MANAGE: "shipment:manage",
  // 红线域:应收款整域只对持 receivable:read 者下发(后端整块门控,非字段级)。
  RECEIVABLE_READ: "receivable:read",

  // ----- 财务:收款单(客户售价侧,非红线,同 receivable:read 域)/ 付款单(红线域)-----
  // 收款:登记/认领/核销/反核销。核销记录内应收额按 D9 门控(无 receivable:read 脱敏为 null)。
  RECEIPT_READ: "receipt:read",
  RECEIPT_MANAGE: "receipt:manage",
  // 红线域:付款关联供应商 + 采购付款金额,整端点只对持 payment:read 者下发(后端脱敏)。
  PAYMENT_READ: "payment:read",
  PAYMENT_MANAGE: "payment:manage",
} as const;

export type PermissionCode = (typeof Permissions)[keyof typeof Permissions];

/** 角色。与后端 app/rbac/constants.py ROLE_META 对齐:ADMIN(系统)/ PRODUCT_OPERATOR(商品)/ SALES(报价)/ PURCHASER(采购)。 */
export const BASE_ROLES: readonly RoleCode[] = ["ADMIN", "PRODUCT_OPERATOR", "SALES", "PURCHASER"] as const;
