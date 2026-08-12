// 销售单前端类型 + API。对齐后端 schemas/sales_order.py。创建走报价 convert;写面 = 整单取消。
import { api } from "./api";
import type { Page } from "./catalog";
import { formatMoney } from "./format";
import type { PurchaseProgress, RelatedPurchaseOrder } from "./purchaseOrder";
import type { StockBalanceLine } from "./inventory";
import type { RelatedOutboundOrder } from "./outboundOrder";
import { qs } from "./qs";

// 镜像后端 SalesOrderStatus:CANCELLED 终态(报价回锁档可重转);更多态留给后续增量。
export type SalesOrderStatus = "CONFIRMED" | "CANCELLED";

/** 销售单行(读)。快照平移自报价行,冻结不变;source_quotation_line_id 记来源报价行。 */
export interface SalesOrderLineOut {
  id: number;
  sales_order_id: number;
  sku_id: number;
  source_quotation_line_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  // 🔴 客户售价红线:无 receivable:read 者后端置 null(PURCHASER / LOGISTICS)。渲染走 formatPrice。
  unit_price: number | string | null;
  qty: number | string;
  line_total: number | string | null;
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
  total_amount: number | string | null;  // 🔴 同上,无 receivable:read → null
  summary: string | null;
  remark: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  updated_at: string;
  // 详情响应附带(GET /{id} 服务端直出),create 响应不含,故可选。
  customer_display?: string;
  salesperson_display?: string;
  source_quotation_no?: string | null;
  // 采购增量扩展:采购进度(详情/列表均附带)。
  purchase_progress?: PurchaseProgress;
  // 关联采购单:仅 purchase:read 者的详情响应附带;SALES 无此字段(不渲染该区块)。
  related_purchase_orders?: RelatedPurchaseOrder[];
  // 库存增量扩展:仅持 inventory:read 者的详情响应附带该键(契约 §3 条件下发);
  // 前端不自判权限,响应键存在与否驱动渲染。
  stock_balances?: StockBalanceLine[];
  // 出库增量扩展:仅持 outbound:read 者的详情响应附带该键(条件下发,同上模式)。
  related_outbound_orders?: RelatedOutboundOrder[];
}

export interface SalesOrderListItem {
  id: number;
  no: string;
  summary: string | null;
  customer_display: string;
  salesperson_display: string;
  status: SalesOrderStatus;
  currency: string;
  total_amount: number | string | null;  // 🔴 同上,无 receivable:read → null
  line_count: number;
  created_at: string;
  // 采购增量扩展:采购进度徽标(列表附带)。
  purchase_progress?: PurchaseProgress;
}

export interface SalesOrderCancelBlockingDocument {
  type: "purchase_order" | "outbound_order";
  id: number;
  no: string;
  status: string;
  path: string;
}

export interface SalesOrderCancelBlockedData {
  blocking_kind?: "purchase_order" | "outbound_order";
  next_action?: string;
  blocking_documents?: SalesOrderCancelBlockingDocument[];
}

/** 🔴 售价红线渲染:null(无 receivable:read)→ 静音「—」,绝不显示 0。镜像采购侧 formatCost。 */
export function formatPrice(v: number | string | null | undefined): string {
  return v === null || v === undefined ? "—" : formatMoney(v);
}

export interface SalesOrderListFilters {
  status?: string;
  customer_id?: number;
  salesperson_id?: number;
  no?: string;
  purchase_progress?: string;
  // 采购台选单入口:只列可发起采购的 SO(排除已采完)。
  purchasable_only?: boolean;
  sort?: "created_at" | "total_amount";
  dir?: "asc" | "desc";
  page?: number;
  size?: number;
}

export const salesOrderApi = {
  list: (p: SalesOrderListFilters) =>
    api.get<Page<SalesOrderListItem>>(`/api/v1/sales-orders${qs(p as Record<string, unknown>)}`),
  get: (id: number) =>
    api.get<{ order: SalesOrderOut; lines: SalesOrderLineOut[] }>(`/api/v1/sales-orders/${id}`),
  // 整单取消(sales:manage):41802/41803 的 data 带真实下游阻塞单据列表。
  cancel: (id: number, reason?: string | null) =>
    api.post<{ order: SalesOrderOut; lines: SalesOrderLineOut[] }>(
      `/api/v1/sales-orders/${id}/cancel`, { reason: reason ?? null }),
};
