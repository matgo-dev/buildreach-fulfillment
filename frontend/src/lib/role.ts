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
  permissions: RolePermissionItem[];
}

export const roleApi = {
  list: () => api.get<RoleOut[]>("/api/v1/roles"),
};
