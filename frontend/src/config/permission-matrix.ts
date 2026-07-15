/**
 * 单一可信源:整个前端的权限相关展示/校验/过滤都从这里读。
 *
 * 与后端 app/rbac/constants.py 等价。后端是权威,前端是 UX 友好层 —
 * 任何冲突以后端为准。
 *
 * 与后端 app/rbac/constants.py 等价。业务域:商品(PRODUCT_OPERATOR)、报价(SALES);
 * ADMIN 不触业务数据(Q25),仅系统域 + 客户管理过渡桥。
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
} as const;

export type PermissionCode = (typeof Permissions)[keyof typeof Permissions];

/** 角色。与后端 app/rbac/constants.py ROLE_META 对齐:ADMIN(系统)/ PRODUCT_OPERATOR(商品)/ SALES(报价)。 */
export const BASE_ROLES: readonly RoleCode[] = ["ADMIN", "PRODUCT_OPERATOR", "SALES"] as const;
