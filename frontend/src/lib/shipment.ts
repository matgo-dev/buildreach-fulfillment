// 发运柜前端类型 + API。对齐后端 schemas/shipment_order.py。
// 本步柜仅承担「组柜容器」角色:船务字段/装船状态机归发运步扩展。无红线字段。
import { api } from "./api";
import type { Page } from "./catalog";
import type { OutboundOrderStatus } from "./outboundOrder";

export type ShipmentStatus = "OPEN" | "CANCELLED";

export interface ShipmentOut {
  id: number;
  no: string;
  container_no: string | null;
  container_type: string | null;
  seal_no: string | null;
  note: string | null;
  status: ShipmentStatus;
  updated_at: string;
  created_at: string;
}

export interface ShipmentListItem {
  id: number;
  no: string;
  container_no: string | null;
  container_type: string | null;
  status: ShipmentStatus;
  /** 柜内出库单数(含草稿,不含已取消)。 */
  outbound_count: number;
  created_at: string;
}

/** 柜内出库单摘要(组柜工作台表)。 */
export interface ShipmentOutboundSummary {
  id: number;
  no: string;
  sales_order_id: number;
  sales_order_no: string;
  // 后端当前柜内摘要未回 customer_display(见集成存疑),可选 + 前端「—」兜底。
  customer_display?: string;
  line_count: number;
  total_qty: number | string;
  status: OutboundOrderStatus;
}

export interface ShipmentDetail {
  shipment: ShipmentOut;
  outbound_orders: ShipmentOutboundSummary[];
}

/** 建 / 改柜入参(POST 与 PATCH 同体;柜号/柜型/封条 OPEN 期可改)。 */
export interface ShipmentSaveBody {
  container_no?: string | null;
  container_type?: string | null;
  seal_no?: string | null;
  note?: string | null;
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface ShipmentListFilters {
  status?: string;
  keyword?: string;
  page?: number;
  size?: number;
}

export const shipmentApi = {
  list: (p: ShipmentListFilters) =>
    api.get<Page<ShipmentListItem>>(`/api/v1/shipments${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<ShipmentDetail>(`/api/v1/shipments/${id}`),
  create: (b: ShipmentSaveBody) => api.post<ShipmentDetail>("/api/v1/shipments", b),
  update: (id: number, b: ShipmentSaveBody) =>
    api.patch<ShipmentDetail>(`/api/v1/shipments/${id}`, b),
  cancel: (id: number) => api.post<ShipmentDetail>(`/api/v1/shipments/${id}/cancel`),
};
