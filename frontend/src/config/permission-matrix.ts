/**
 * 单一可信源:整个前端的权限相关展示/校验/过滤都从这里读。
 *
 * 与后端 app/rbac/constants.py 等价。后端是权威,前端是 UX 友好层 —
 * 任何冲突以后端为准。
 *
 * M0 基座:仅 auth:* + system:* 两组,仅 ADMIN 一个角色,无业务权限点。
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

  // ----- 履约:商品(SPU+SKU)-----
  PRODUCT_READ: "product:read",
  PRODUCT_MANAGE: "product:manage",
} as const;

export type PermissionCode = (typeof Permissions)[keyof typeof Permissions];

/** 角色。与后端 app/rbac/constants.py ROLE_META 对齐(ADMIN 不触业务数据,商品由 PRODUCT_OPERATOR 管)。 */
export const BASE_ROLES: readonly RoleCode[] = ["ADMIN", "PRODUCT_OPERATOR"] as const;
