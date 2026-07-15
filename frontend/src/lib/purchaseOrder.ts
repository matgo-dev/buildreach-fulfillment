// 采购单前端类型 + API。对齐后端 schemas/purchase_order.py。
// 红线字段(unit_price / line_total / total_amount)后端对无 purchase:read_cost 者脱敏为 null;
// 前端只需把 null 渲染成「—」(见 formatCost),不做任何客户端隐藏逻辑。
import { ApiError, api } from "./api";
import type { Page } from "./catalog";
import { formatMoney } from "./salesOrder";

export type PurchaseOrderStatus = "DRAFT" | "CONFIRMED" | "CANCELLED";

/** 采购进度(销售单相对采购覆盖度的派生态)。 */
export type PurchaseProgress = "NOT_ORDERED" | "PARTIALLY_ORDERED" | "FULLY_ORDERED";

export interface PurchaseOrderOut {
  id: number;
  no: string;
  source_sales_order_id: number;
  supplier_id: number;
  currency: string;
  status: PurchaseOrderStatus;
  /** 红线:无 read_cost 时后端下发 null。 */
  total_amount: number | string | null;
  remark: string | null;
  updated_at: string;
  supplier_display?: string;
  source_sales_order_no?: string | null;
}

export interface PurchaseOrderLineOut {
  id: number;
  purchase_order_id: number;
  sku_id: number;
  source_sales_order_line_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  /** 红线:无 read_cost 时 null。 */
  unit_price: number | string | null;
  qty: number | string;
  /** 红线:无 read_cost 时 null。 */
  line_total: number | string | null;
  language: string;
  sort_order: number;
  remark: string | null;
}

export interface PurchaseOrderListItem {
  id: number;
  no: string;
  source_sales_order_id: number;
  source_sales_order_no: string | null;
  supplier_id: number;
  supplier_display: string;
  status: PurchaseOrderStatus;
  currency: string;
  /** 红线:无 read_cost 时 null。 */
  total_amount: number | string | null;
  line_count: number;
  created_at: string;
}

/** 建单器可采行(GET /purchase-orders/purchasable-lines)。 */
export interface PurchasableLine {
  source_sales_order_line_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  required_qty: number | string;
  covered_qty: number | string;
  remaining_qty: number | string;
  /** 建议采购价(销售报价单价);无成本权限或缺省时 null。 */
  default_unit_price: number | string | null;
}

/** 写入行(id 有值=既有采购行对账更新;无 id=新增)。 */
export interface PurchaseOrderLineIn {
  id?: number;
  source_sales_order_line_id: number;
  qty: number;
  unit_price: number;
  remark?: string | null;
  sort_order?: number;
}

export interface PurchaseOrderCreateBody {
  source_sales_order_id: number;
  supplier_id: number;
  currency: string;
  remark?: string | null;
  lines: PurchaseOrderLineIn[];
}

/** PUT 必带乐观锁基线(= 上次 GET 的 order.updated_at)。 */
export interface PurchaseOrderUpdateBody {
  supplier_id: number;
  currency: string;
  remark?: string | null;
  lines: PurchaseOrderLineIn[];
  expected_updated_at: string;
}

/** 关联采购单(SO 详情附带,仅 purchase:read 者可见)。 */
export interface RelatedPurchaseOrder {
  id: number;
  no: string;
  status: PurchaseOrderStatus;
  supplier_id: number;
  supplier_display: string;
  currency: string;
  total_amount: number | string | null;
}

/** 红线金额渲染:null(无成本权限)→ 静音「—」,绝不显示 0。 */
export function formatCost(v: number | string | null | undefined): string {
  return v === null || v === undefined ? "—" : formatMoney(v);
}

// 后端错误码 → 中文 toast。未列出的沿用后端 message。
const PURCHASE_ERROR_MESSAGES: Record<number, string> = {
  41603: "数量超过销售单剩余额度",
  41606: "供应商已停用,不可选用",
  41604: "来源销售单无效",
  41605: "采购单已被他人修改,请刷新后重试",
  41607: "仅草稿可编辑 / 删除",
  41608: "采购单至少需要一行",
  41501: "供应商不存在",
};

export function purchaseErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError && PURCHASE_ERROR_MESSAGES[e.code]) return PURCHASE_ERROR_MESSAGES[e.code];
  return e instanceof Error ? e.message : fallback;
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface PurchaseOrderListFilters {
  status?: string;
  supplier_id?: number;
  source_sales_order_id?: number;
  page?: number;
  size?: number;
}

export const purchaseOrderApi = {
  list: (p: PurchaseOrderListFilters) =>
    api.get<Page<PurchaseOrderListItem>>(`/api/v1/purchase-orders${qs(p as Record<string, unknown>)}`),
  get: (id: number) =>
    api.get<{ order: PurchaseOrderOut; lines: PurchaseOrderLineOut[] }>(`/api/v1/purchase-orders/${id}`),
  purchasableLines: (sourceSalesOrderId: number) =>
    api.get<{ items: PurchasableLine[] }>(
      `/api/v1/purchase-orders/purchasable-lines?source_sales_order_id=${sourceSalesOrderId}`,
    ),
  create: (b: PurchaseOrderCreateBody) =>
    api.post<{ order: PurchaseOrderOut; lines: PurchaseOrderLineOut[] }>("/api/v1/purchase-orders", b),
  update: (id: number, b: PurchaseOrderUpdateBody) =>
    api.put<{ order: PurchaseOrderOut; lines: PurchaseOrderLineOut[] }>(`/api/v1/purchase-orders/${id}`, b),
  del: (id: number) => api.del<null>(`/api/v1/purchase-orders/${id}`),
  confirm: (id: number) =>
    api.post<{ order: PurchaseOrderOut; lines: PurchaseOrderLineOut[] }>(`/api/v1/purchase-orders/${id}/confirm`),
  cancel: (id: number) =>
    api.post<{ order: PurchaseOrderOut; lines: PurchaseOrderLineOut[] }>(`/api/v1/purchase-orders/${id}/cancel`),
};
