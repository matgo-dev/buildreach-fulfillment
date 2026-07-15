// 销售单前端类型 + API。对齐后端 schemas/sales_order.py。本增量只读(创建走报价 convert)。
import { api } from "./api";
import type { Page } from "./catalog";
import type { PurchaseProgress, RelatedPurchaseOrder } from "./purchaseOrder";

// 本增量仅初始态;完整 SO 状态机(→采购中…)留给转采购增量。
export type SalesOrderStatus = "CONFIRMED";

/** 销售单行(读)。快照平移自报价行,冻结不变;source_quotation_line_id 记来源报价行。 */
export interface SalesOrderLineOut {
  id: number;
  sales_order_id: number;
  sku_id: number;
  source_quotation_line_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  unit_price: number | string;
  qty: number | string;
  line_total: number | string;
  remark: string | null;
  language: string;
  sort_order: number;
  // 采购增量扩展:该行已被采购覆盖的数量(非红线,始终可见)。剩余 = qty − covered_qty。
  covered_qty?: number | string;
}

export interface SalesOrderOut {
  id: number;
  no: string;
  source_quotation_id: number;
  customer_id: number;
  salesperson_id: number;
  language: string;
  currency: string;
  status: SalesOrderStatus;
  total_amount: number | string;
  summary: string | null;
  remark: string | null;
  updated_at: string;
  // 详情响应附带(GET /{id} 服务端直出),create 响应不含,故可选。
  customer_display?: string;
  salesperson_display?: string;
  source_quotation_no?: string | null;
  // 采购增量扩展:采购进度(详情/列表均附带)。
  purchase_progress?: PurchaseProgress;
  // 关联采购单:仅 purchase:read 者的详情响应附带;SALES 无此字段(不渲染该区块)。
  related_purchase_orders?: RelatedPurchaseOrder[];
}

export interface SalesOrderListItem {
  id: number;
  no: string;
  summary: string | null;
  customer_display: string;
  salesperson_display: string;
  status: SalesOrderStatus;
  currency: string;
  total_amount: number | string;
  line_count: number;
  created_at: string;
  // 采购增量扩展:采购进度徽标(列表附带)。
  purchase_progress?: PurchaseProgress;
}

export interface SalesOrderListFilters {
  status?: string;
  customer_id?: number;
  salesperson_id?: number;
  purchase_progress?: string;
  sort?: "created_at" | "total_amount";
  dir?: "asc" | "desc";
  page?: number;
  size?: number;
}

/** 金额格式化:固定 2 位小数(单价/金额/总额)。 */
export function formatMoney(v: number | string): string {
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 });
}

/** 数量格式化:最多 3 位小数、不补零(qty 为 Numeric(18,3),整数不应显示成 x.00)。 */
export function formatQty(v: number | string): string {
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const salesOrderApi = {
  list: (p: SalesOrderListFilters) =>
    api.get<Page<SalesOrderListItem>>(`/api/v1/sales-orders${qs(p as Record<string, unknown>)}`),
  get: (id: number) =>
    api.get<{ order: SalesOrderOut; lines: SalesOrderLineOut[] }>(`/api/v1/sales-orders/${id}`),
};
