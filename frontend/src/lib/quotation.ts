// 报价单前端类型 + API。对齐后端 schemas/quotation.py。
import { api } from "./api";
import type { Page } from "./catalog";

export type QuotationStatus = "DRAFT" | "LOCKED" | "CONVERTED" | "VOID";

/** 报价行(读)。快照字段是下单那刻冻结的展示串,不随主数据变。 */
export interface QuotationLineOut {
  id: number;
  quotation_order_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  unit_price: number | string;
  qty: number | string;
  line_total: number | string;
  remark: string | null;
  language: string;
  sort_order: number;
}

export interface QuotationOrderOut {
  id: number;
  no: string;
  customer_id: number;
  salesperson_id: number;
  language: string;
  currency: string;
  valid_until: string | null;
  status: QuotationStatus;
  total_amount: number | string;
  summary: string | null;
  remark: string | null;
  updated_at: string;
  // 详情响应附带的展示名(GET /{id} 服务端按 id 直查,不受"可选报价人"口径限制);
  // create/update 响应不含,故可选。
  customer_display?: string;
  salesperson_display?: string;
}

export interface QuotationListItem {
  id: number;
  no: string;
  summary: string | null;
  customer_display: string;
  salesperson_display: string;
  status: QuotationStatus;
  currency: string;
  total_amount: number | string;
  valid_until: string | null;
  line_count: number;
  created_at: string;
}

/** 保存时的行(id 有值=已加载行,对账更新;无 id=新增)。 */
export interface QuotationLineIn {
  id?: number;
  sku_id: number;
  unit_price: number;
  qty: number;
  remark?: string | null;
  sort_order?: number;
}

export interface QuotationSaveBody {
  customer_id: number;
  currency: string;
  salesperson_id?: number | null;
  valid_until?: string | null;
  summary?: string | null;
  language?: string | null;
  remark?: string | null;
  lines: QuotationLineIn[];
}

/** PUT 必带乐观锁基线。 */
export type QuotationUpdateBody = QuotationSaveBody & { expected_updated_at: string };

export interface SelectableUser {
  id: number;
  name: string;
}

export interface QuotationListFilters {
  status?: string;
  customer_id?: number;
  salesperson_id?: number;
  keyword?: string;
  created_from?: string;
  created_to?: string;
  sort?: "created_at" | "total_amount";
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

export const quotationApi = {
  list: (p: QuotationListFilters) =>
    api.get<Page<QuotationListItem>>(`/api/v1/quotations${qs(p as Record<string, unknown>)}`),
  get: (id: number) =>
    api.get<{ order: QuotationOrderOut; lines: QuotationLineOut[] }>(`/api/v1/quotations/${id}`),
  create: (b: QuotationSaveBody) => api.post<QuotationOrderOut>("/api/v1/quotations", b),
  update: (id: number, b: QuotationUpdateBody) =>
    api.put<QuotationOrderOut>(`/api/v1/quotations/${id}`, b),
  del: (id: number) => api.del<null>(`/api/v1/quotations/${id}`),
  lock: (id: number) => api.post<QuotationOrderOut>(`/api/v1/quotations/${id}/lock`),
  unlock: (id: number) => api.post<QuotationOrderOut>(`/api/v1/quotations/${id}/unlock`),
  void: (id: number, reason?: string) =>
    api.post<QuotationOrderOut>(`/api/v1/quotations/${id}/void`, { reason }),
  usersSelectable: () => api.get<SelectableUser[]>("/api/v1/users/selectable"),
};
