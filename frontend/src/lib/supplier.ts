// 供应商主数据前端类型 + API。对齐后端 schemas/supplier.py。
import { api } from "./api";
import type { Page } from "./catalog";

export type SupplierStatus = "ACTIVE" | "INACTIVE";

/** 状态徽标映射(镜像 UI 呈现,非业务规则)。ACTIVE=启用 / INACTIVE=停用。 */
export const SUPPLIER_STATUS_META: Record<SupplierStatus, { label: string; color: string }> = {
  ACTIVE: { label: "启用", color: "success" },
  INACTIVE: { label: "停用", color: "default" },
};

export interface SupplierOut {
  id: number;
  code: string;
  name: string;
  default_currency: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  address: string | null;
  status: SupplierStatus;
}

export interface SupplierListItem {
  id: number;
  code: string;
  name: string;
  default_currency: string | null;
  contact_name: string | null;
  status: SupplierStatus;
  updated_at: string;
}

/** 建 / 改供应商入参(POST 与 PUT 同体)。 */
export interface SupplierSaveBody {
  name: string;
  default_currency?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  contact_email?: string | null;
  address?: string | null;
}

export interface SupplierListFilters {
  status?: string;
  q?: string;
  page?: number;
  size?: number;
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const supplierApi = {
  list: (p: SupplierListFilters) =>
    api.get<Page<SupplierListItem>>(`/api/v1/suppliers${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<SupplierOut>(`/api/v1/suppliers/${id}`),
  create: (b: SupplierSaveBody) => api.post<SupplierOut>("/api/v1/suppliers", b),
  update: (id: number, b: SupplierSaveBody) => api.put<SupplierOut>(`/api/v1/suppliers/${id}`, b),
  activate: (id: number) => api.post<SupplierOut>(`/api/v1/suppliers/${id}/activate`),
  deactivate: (id: number) => api.post<SupplierOut>(`/api/v1/suppliers/${id}/deactivate`),
};
