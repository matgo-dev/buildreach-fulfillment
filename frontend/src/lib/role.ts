// 角色权限矩阵(只读)前端类型 + API。对齐后端 schemas/role.py。
import { api } from "./api";

export interface RolePermissionItem {
  code: string;
  name: string;
  module: string;
}

export interface RoleOut {
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  is_custom_readonly: boolean;
  permissions: RolePermissionItem[];
}

export interface RoleCustomBody {
  code?: string;
  name: string;
  description?: string | null;
  permissions: string[];
}

export const roleApi = {
  list: () => api.get<RoleOut[]>("/api/v1/roles"),
  assignablePermissions: () => api.get<RolePermissionItem[]>("/api/v1/roles/assignable-permissions"),
  create: (b: RoleCustomBody) => api.post<RoleOut>("/api/v1/roles", b),
  update: (code: string, b: RoleCustomBody) => api.put<RoleOut>(`/api/v1/roles/${code}`, b),
  delete: (code: string) => api.del<null>(`/api/v1/roles/${code}`),
};
