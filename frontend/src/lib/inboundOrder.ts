// 入库单前端类型 + API。对齐后端 schemas/inbound_order.py。
// 🔴 入库单据/行**无任何成本字段**(契约 D3)—— 读投影天然无红线,前端不渲染任何价格列。
// 详情内嵌 PO 摘要的成本由后端按 purchase:read_cost 脱敏为 null;payable 块仅在响应含该键时渲染。
import { ApiError, api } from "./api";
import type { Page } from "./catalog";
import type { PurchaseOrderOut } from "./purchaseOrder";
import type { PayableOut } from "./payable";

export type InboundOrderStatus = "IN_TRANSIT" | "RECEIVED" | "CANCELLED";

export interface InboundOrderOut {
  id: number;
  no: string;
  purchase_order_id: number;
  status: InboundOrderStatus;
  carrier_name: string | null;
  tracking_no: string | null;
  shipped_at: string | null;
  eta: string | null;
  arrived_at: string | null;
  remark: string | null;
  updated_at: string;
  purchase_order_no: string;
  supplier_display: string;
}

export interface InboundOrderLineOut {
  id: number;
  inbound_order_id: number;
  purchase_order_line_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  language: string;
  qty: number | string;
  sort_order: number;
  remark: string | null;
}

export interface InboundOrderListItem {
  id: number;
  no: string;
  purchase_order_id: number;
  purchase_order_no: string;
  supplier_display: string;
  status: InboundOrderStatus;
  carrier_name: string | null;
  tracking_no: string | null;
  eta: string | null;
  arrived_at: string | null;
  line_count: number;
  total_qty: number | string;
  created_at: string;
}

/** 建单器数据源(GET /inbound-orders/receivable-lines)。无成本字段。 */
export interface ReceivableLine {
  purchase_order_line_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  language: string;
  ordered_qty: number | string;
  in_transit_qty: number | string;
  received_qty: number | string;
  remaining_qty: number | string;
}

/** 入库详情返回(payable 仅在持 payable:read 且已入库时存在;前端按键存在与否渲染)。 */
export interface InboundOrderDetail {
  order: InboundOrderOut;
  lines: InboundOrderLineOut[];
  purchase_order: PurchaseOrderOut;
  payable?: PayableOut;
}

/** 写入行(引用 PO 行 + 本次入库数量)。 */
export interface InboundOrderLineIn {
  purchase_order_line_id: number;
  qty: number;
  remark?: string | null;
  sort_order?: number;
}

export interface InboundOrderCreateBody {
  purchase_order_id: number;
  carrier_name?: string | null;
  tracking_no?: string | null;
  shipped_at?: string | null;
  eta?: string | null;
  remark?: string | null;
  lines: InboundOrderLineIn[];
}

export interface InboundOrderUpdateBody {
  carrier_name?: string | null;
  tracking_no?: string | null;
  shipped_at?: string | null;
  eta?: string | null;
  remark?: string | null;
  lines: InboundOrderLineIn[];
}

// 后端错误码 → 中文 toast(镜像 exceptions.py 段 16/17)。未列出的沿用后端 message。
const INBOUND_ERROR_MESSAGES: Record<number, string> = {
  41609: "该采购单存在活动入库单,不可取消",
  41701: "入库单不存在",
  41702: "来源采购单无效或未确认",
  41703: "入库数量超过采购单剩余可收额度",
  41704: "非法的入库单状态流转",
  41705: "仅在途入库单可编辑",
  41706: "入库行引用的采购行不属于该采购单",
  41707: "入库单至少需要一行",
  41708: "对应应付款已有核销,不可撤销入库",
};

export function inboundErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError && INBOUND_ERROR_MESSAGES[e.code]) return INBOUND_ERROR_MESSAGES[e.code];
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

export interface InboundOrderListFilters {
  status?: string;
  purchase_order_id?: number;
  supplier_id?: number;
  keyword?: string;
  page?: number;
  size?: number;
}

export const inboundOrderApi = {
  list: (p: InboundOrderListFilters) =>
    api.get<Page<InboundOrderListItem>>(`/api/v1/inbound-orders${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<InboundOrderDetail>(`/api/v1/inbound-orders/${id}`),
  receivableLines: (purchaseOrderId: number) =>
    api.get<{ items: ReceivableLine[] }>(
      `/api/v1/inbound-orders/receivable-lines?purchase_order_id=${purchaseOrderId}`,
    ),
  create: (b: InboundOrderCreateBody) =>
    api.post<InboundOrderDetail>("/api/v1/inbound-orders", b),
  update: (id: number, b: InboundOrderUpdateBody) =>
    api.put<InboundOrderDetail>(`/api/v1/inbound-orders/${id}`, b),
  receive: (id: number, arrived_at?: string | null) =>
    api.post<InboundOrderDetail>(`/api/v1/inbound-orders/${id}/receive`, { arrived_at: arrived_at ?? null }),
  unreceive: (id: number, void_reason?: string | null) =>
    api.post<InboundOrderDetail>(`/api/v1/inbound-orders/${id}/unreceive`, { void_reason: void_reason ?? null }),
  cancel: (id: number) => api.post<InboundOrderDetail>(`/api/v1/inbound-orders/${id}/cancel`),
};
