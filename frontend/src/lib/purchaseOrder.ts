// 采购单前端类型 + API。对齐后端 schemas/purchase_order.py。
// 红线字段(unit_price / line_total / total_amount)后端对无 purchase:read_cost 者脱敏为 null;
// 前端只需把 null 渲染成「—」(见 formatCost),不做任何客户端隐藏逻辑。
import { api } from "./api";
import type { Page } from "./catalog";
import { formatMoney } from "./format";
import { qs } from "./qs";

export type PurchaseOrderStatus = "DRAFT" | "CONFIRMED" | "CANCELLED";

/** 采购进度(销售单相对采购覆盖度的派生态)。 */
export type PurchaseProgress = "NOT_ORDERED" | "PARTIALLY_ORDERED" | "FULLY_ORDERED";

/** 收货进度(采购单相对入库覆盖度的派生态;入库步为 PO 详情/列表新增)。 */
export type ReceiptProgress = "NOT_RECEIVED" | "PARTIALLY_RECEIVED" | "FULLY_RECEIVED";

/** PO 详情「入库记录区」项(含 CANCELLED 并标状态,可追溯)。无成本字段。 */
export interface RelatedInboundOrder {
  id: number;
  no: string;
  status: "IN_TRANSIT" | "RECEIVED" | "CANCELLED";
  carrier_name: string | null;
  tracking_no: string | null;
  eta: string | null;
  arrived_at: string | null;
  created_at: string;
}

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
  /** 收货进度(入库步新增,详情响应附带)。 */
  receipt_progress?: ReceiptProgress;
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
  /** 入库覆盖度(入库步新增,详情响应附带每行)。 */
  received_qty?: number | string;
  in_transit_qty?: number | string;
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
  /** 收货进度徽标(入库步新增,列表响应附带)。 */
  receipt_progress?: ReceiptProgress | null;
  /** 次要在途信号:已登记未收货的入库单数(与收货进度互补,回答「有几张货在路上」)。 */
  in_transit_count?: number;
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

export interface PurchaseOrderListFilters {
  status?: string;
  supplier_id?: number;
  source_sales_order_id?: number;
  source_sales_order_no?: string;
  /** 合并搜:采购单号 OR 来源销售单号(入库选单器用一个框)。 */
  q?: string;
  /** 仅列「还有未收量」的 PO,隐藏已全部入库的死单(入库选单器用)。 */
  receivable_only?: boolean;
  page?: number;
  size?: number;
}

export const purchaseOrderApi = {
  list: (p: PurchaseOrderListFilters) =>
    api.get<Page<PurchaseOrderListItem>>(`/api/v1/purchase-orders${qs(p as Record<string, unknown>)}`),
  get: (id: number) =>
    api.get<{ order: PurchaseOrderOut; lines: PurchaseOrderLineOut[]; inbound_orders: RelatedInboundOrder[] }>(
      `/api/v1/purchase-orders/${id}`,
    ),
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
