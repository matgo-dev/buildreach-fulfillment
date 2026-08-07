// 用户管理前端类型 + API。对齐后端 schemas/user.py(AdminUser*)。
import { api } from "./api";
import type { RoleCode } from "./auth";
import type { Page } from "./catalog";
import { qs } from "./qs";

export type UserStatus = "ACTIVE" | "DISABLED" | "DEACTIVATED";

/** 状态徽标映射(镜像 UI 呈现,非业务规则)。DEACTIVATED=自助注销(历史态,列表可见)。 */
export const USER_STATUS_META: Record<UserStatus, { label: string; color: string }> = {
  ACTIVE: { label: "启用", color: "success" },
  DISABLED: { label: "停用", color: "default" },
  DEACTIVATED: { label: "已注销", color: "warning" },
};

/**
 * 内部角色 code→中文(声明式镜像后端 rbac/constants.py ROLE_META;权威在后端)。
 * `satisfies Record<RoleCode, string>` 强制与 RoleCode 集合完备对齐——后端新增角色
 * 时,漏更这里会是编译错误,杜绝角色下拉与类型静默漂移。
 */
export const ROLE_META = {
  ADMIN: "系统管理员",
  PRODUCT_OPERATOR: "商品运营",
  SALES: "销售",
  PURCHASER: "采购员",
  LOGISTICS: "物流仓运",
  FINANCE: "财务",
} satisfies Record<RoleCode, string>;

export const ROLE_OPTIONS = Object.entries(ROLE_META).map(([value, label]) => ({ value, label }));

export function roleLabel(code: string): string {
  return (ROLE_META as Record<string, string>)[code] ?? code;
}

export interface UserItem {
  id: number;
  email: string | null;
  phone: string | null;
  username: string | null;
  name: string;
  status: UserStatus;
  must_change_password: boolean;
  roles: string[];
}

/** 建号入参(roles 白名单由后端 service 校验)。 */
export interface UserCreateBody {
  email: string;
  username?: string | null;
  name: string;
  password: string;
  roles: string[];
  must_change_password?: boolean;
}

export interface UserUpdateBody {
  email?: string | null;
  phone?: string | null;
  name?: string | null;
}

export interface UserListFilters {
  q?: string;
  status?: string;
  page?: number;
  size?: number;
}

export const userAdminApi = {
  list: (p: UserListFilters) =>
    api.get<Page<UserItem>>(`/api/v1/users${qs(p as Record<string, unknown>)}`),
  create: (b: UserCreateBody) => api.post<UserItem>("/api/v1/users", b),
  update: (id: number, b: UserUpdateBody) => api.put<UserItem>(`/api/v1/users/${id}`, b),
  disable: (id: number) => api.post<UserItem>(`/api/v1/users/${id}/disable`),
  enable: (id: number) => api.post<UserItem>(`/api/v1/users/${id}/enable`),
  resetPassword: (id: number, password: string) =>
    api.post<UserItem>(`/api/v1/users/${id}/reset-password`, { password }),
  changeRoles: (id: number, roles: string[]) =>
    api.put<UserItem>(`/api/v1/users/${id}/roles`, { roles }),
  changeRole: (id: number, role: string) =>
    api.put<UserItem>(`/api/v1/users/${id}/role`, { role }),
};
