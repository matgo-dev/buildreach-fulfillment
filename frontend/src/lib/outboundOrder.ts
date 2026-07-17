// 出库单前端类型 + API。对齐后端 schemas/outbound_order.py。
// 🔴 出库单据/行**无任何售价/成本字段**(契约 §3 红线):出库单是纯仓单,全链路不带售价与成本。
// 出库行本身不存快照,展示字段(name/spec/unit)由后端 join SO 行回填(契约 §1.3 单一源头)。
import { api } from "./api";
import type { Page } from "./catalog";

export type OutboundOrderStatus = "DRAFT" | "ISSUED" | "CANCELLED";

/** 出库单行(读)。快照字段来自后端 join CONFIRMED SO 行(冻结),出库行不复制快照。 */
export interface OutboundOrderLineOut {
  id: number;
  outbound_order_id: number;
  sales_order_line_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  qty: number | string;
}

export interface OutboundOrderOut {
  id: number;
  no: string;
  sales_order_id: number;
  shipment_id: number;
  status: OutboundOrderStatus;
  issued_at: string | null;
  note: string | null;
  updated_at: string;
  // 详情响应附带的溯源展示字段。
  sales_order_no: string;
  shipment_no: string | null;
  container_no: string | null;
}

export interface OutboundOrderListItem {
  id: number;
  no: string;
  sales_order_id: number;
  sales_order_no: string;
  shipment_id: number;
  shipment_no: string | null;
  container_no: string | null;
  status: OutboundOrderStatus;
  line_count: number;
  total_qty: number | string;
  issued_at: string | null;
  created_at: string;
}

/** 建单器数据源(GET /sales-orders/{id}/outboundable-lines)。available_qty = 可发。无售价字段。 */
export interface OutboundableLine {
  sales_order_line_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  language: string;
  ordered_qty: number | string;
  inbound_qty: number | string;
  outbound_qty: number | string;
  available_qty: number | string;
}

export interface OutboundOrderDetail {
  order: OutboundOrderOut;
  lines: OutboundOrderLineOut[];
}

/** SO 详情「关联出库单」项(仅 outbound:read 者的 SO 详情响应附带;含 CANCELLED 可追溯;无金额)。 */
export interface RelatedOutboundOrder {
  id: number;
  no: string;
  status: OutboundOrderStatus;
  shipment_id: number;
  shipment_no: string;
  container_no: string | null;
  issued_at: string | null;
}

/** 写入行(引用 SO 行 + 本次出库数量)。 */
export interface OutboundOrderLineIn {
  sales_order_line_id: number;
  qty: number;
  sort_order?: number;
}

/** 建单(柜详情内发起):锚定单一柜 + 单一 SO,一柜内每来源 SO 各一张(后端偏唯一)。 */
export interface OutboundOrderCreateBody {
  shipment_id: number;
  sales_order_id: number;
  note?: string | null;
  lines: OutboundOrderLineIn[];
}

/** 草稿整单保存(携乐观锁基线,冲突 409 → 后端 message)。柜/SO 锚定不可改,仅改行 + 备注。 */
export interface OutboundOrderUpdateBody {
  note?: string | null;
  lines: OutboundOrderLineIn[];
  /** 乐观锁基线 = 打开编辑时的 order.updated_at(对齐 PO / 入库)。 */
  expected_updated_at: string;
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface OutboundOrderListFilters {
  status?: string;
  shipment_id?: number;
  sales_order_id?: number;
  keyword?: string;
  page?: number;
  size?: number;
}

export const outboundOrderApi = {
  list: (p: OutboundOrderListFilters) =>
    api.get<Page<OutboundOrderListItem>>(`/api/v1/outbound-orders${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<OutboundOrderDetail>(`/api/v1/outbound-orders/${id}`),
  /** 建单器数据源:某 SO 的可发行 + 每行可发数量(须 outbound:manage)。 */
  outboundableLines: (salesOrderId: number) =>
    api.get<{ items: OutboundableLine[] }>(
      `/api/v1/sales-orders/${salesOrderId}/outboundable-lines`,
    ),
  create: (b: OutboundOrderCreateBody) =>
    api.post<OutboundOrderDetail>("/api/v1/outbound-orders", b),
  update: (id: number, b: OutboundOrderUpdateBody) =>
    api.put<OutboundOrderDetail>(`/api/v1/outbound-orders/${id}`, b),
  confirm: (id: number) => api.post<OutboundOrderDetail>(`/api/v1/outbound-orders/${id}/confirm`),
  revert: (id: number, void_reason?: string | null) =>
    api.post<OutboundOrderDetail>(`/api/v1/outbound-orders/${id}/revert`, {
      void_reason: void_reason ?? null,
    }),
  cancel: (id: number) => api.post<OutboundOrderDetail>(`/api/v1/outbound-orders/${id}/cancel`),
};
