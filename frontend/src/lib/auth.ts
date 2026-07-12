// 认证相关类型与 API 调用。M0 基座:仅登录链路,无自助注册。

import { api } from "./api";

export type RoleCode = "ADMIN" | "PRODUCT_OPERATOR";

export interface MeData {
  id: number;
  email: string;
  name: string;
  must_change_password: boolean;
  roles: RoleCode[];
  permissions: string[];
}

export interface LoginResult {
  /** access token,前端存 Zustand(内存 + sessionStorage 兜底) */
  access_token: string;
  token_type: string;
  expires_in: number;
  /** refresh token 由后端通过 httpOnly cookie 下发,前端 JS 读不到 */
}

export const authApi = {
  login: (identifier: string, password: string) =>
    api.post<LoginResult>("/api/v1/auth/login", { identifier, password }, { noAuth: true }),

  me: () => api.get<MeData>("/api/v1/auth/me"),

  logout: () => api.post<null>("/api/v1/auth/logout"),

  changePassword: (old_password: string, new_password: string) =>
    api.post<LoginResult>("/api/v1/auth/change-password", { old_password, new_password }),
};
