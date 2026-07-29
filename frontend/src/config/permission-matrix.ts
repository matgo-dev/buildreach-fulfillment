/**
 * AUTO-GENERATED —— 由 backend/scripts/gen_frontend_permissions.py 从
 * backend/app/rbac/constants.py 生成。请勿手改。
 *
 * 后端 constants.py 是权限码的唯一权威源;本文件与 DB permissions 表(启动 sync)同为其派生。
 * 新增/修改权限码:改后端 constants.py + PERMISSION_META,再重跑生成脚本(CI 会卡未重生成)。
 * 前端 <Can perm={Permissions.X}> 引用此处;真正的门控在后端每个端点。
 */

export const Permissions = {
  // auth
  AUTH_LOGIN: "auth:login",
  AUTH_LOGOUT: "auth:logout",
  AUTH_ME: "auth:me",
  // system
  USER_MANAGE: "user:manage",
  ROLE_MANAGE: "role:manage",
  PERMISSION_MANAGE: "permission:manage",
  SYSTEM_CONFIG: "system:config",
  SYSTEM_AUDIT: "system:audit",
  // fulfillment
  CUSTOMER_MANAGE: "customer:manage",
  CUSTOMER_READ: "customer:read",
  PRODUCT_READ: "product:read",
  PRODUCT_MANAGE: "product:manage",
  QUOTE_MANAGE: "quote:manage",
  SALES_READ: "sales:read",
  SALES_MANAGE: "sales:manage",
  SUPPLIER_MANAGE: "supplier:manage",
  SUPPLIER_READ: "supplier:read",
  PURCHASE_MANAGE: "purchase:manage",
  PURCHASE_READ: "purchase:read",
  PURCHASE_READ_COST: "purchase:read_cost",
  INBOUND_MANAGE: "inbound:manage",
  INBOUND_READ: "inbound:read",
  PAYABLE_READ: "payable:read",
  INVENTORY_READ: "inventory:read",
  OUTBOUND_READ: "outbound:read",
  OUTBOUND_MANAGE: "outbound:manage",
  SHIPMENT_READ: "shipment:read",
  SHIPMENT_MANAGE: "shipment:manage",
  RECEIVABLE_READ: "receivable:read",
  RECEIPT_READ: "receipt:read",
  RECEIPT_MANAGE: "receipt:manage",
  PAYMENT_READ: "payment:read",
  PAYMENT_MANAGE: "payment:manage",
} as const;

export type PermissionCode = (typeof Permissions)[keyof typeof Permissions];
