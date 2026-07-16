// 客户主数据前端类型 + API。对齐后端 schemas/customer.py。
import { api } from "./api";
import type { Page } from "./catalog";

export type CustomerStatus = "ACTIVE" | "INACTIVE";

/** 状态徽标映射(镜像 UI 呈现,非业务规则)。ACTIVE=启用 / INACTIVE=停用。 */
export const CUSTOMER_STATUS_META: Record<CustomerStatus, { label: string; color: string }> = {
  ACTIVE: { label: "启用", color: "success" },
  INACTIVE: { label: "停用", color: "default" },
};

export interface CustomerOut {
  id: number;
  code: string;
  name: string;
  quote_language: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  address: string | null;
  status: CustomerStatus;
}

export interface CustomerListItem {
  id: number;
  code: string;
  name: string;
  quote_language: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  status: CustomerStatus;
  updated_at: string;
}

/** 建 / 改客户入参(POST 与 PUT 同体;code 身份键不可改,不在此)。 */
export interface CustomerSaveBody {
  name: string;
  quote_language?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  contact_email?: string | null;
  address?: string | null;
}

export interface CustomerListFilters {
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

export const customerApi = {
  list: (p: CustomerListFilters) =>
    api.get<Page<CustomerListItem>>(`/api/v1/customers${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<CustomerOut>(`/api/v1/customers/${id}`),
  create: (b: CustomerSaveBody) => api.post<CustomerOut>("/api/v1/customers", b),
  update: (id: number, b: CustomerSaveBody) => api.put<CustomerOut>(`/api/v1/customers/${id}`, b),
  activate: (id: number) => api.post<CustomerOut>(`/api/v1/customers/${id}/activate`),
  deactivate: (id: number) => api.post<CustomerOut>(`/api/v1/customers/${id}/deactivate`),
};
