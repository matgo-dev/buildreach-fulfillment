import { api } from "./api";
import type { Page } from "./catalog";
import { qs } from "./qs";

export type ReverseRequestStatus = "PENDING_REVIEW" | "APPROVED" | "REJECTED" | "COMPLETED";
export type ReverseRequestType = "FULFILLMENT_CANCEL";
export type ReverseGoodsStatus = "IN_TRANSIT" | "RECEIVED";
export type ReverseSupplierResolution = "SUPPLIER_ACCEPTS_RETURN" | "COMPANY_BEAR_LOSS";

export interface ReverseRequestOut {
  id: number;
  no: string;
  request_type: ReverseRequestType;
  status: ReverseRequestStatus;
  sales_order_id: number;
  purchase_order_id: number;
  inbound_order_id: number;
  goods_status: ReverseGoodsStatus;
  supplier_resolution: ReverseSupplierResolution | null;
  reason: string;
  review_note: string | null;
  completion_note: string | null;
  created_at: string;
  updated_at: string;
  reviewed_at: string | null;
  completed_at: string | null;
  sales_order_no?: string | null;
  purchase_order_no?: string | null;
  inbound_order_no?: string | null;
  customer_display?: string | null;
  supplier_display?: string | null;
}

export interface ReverseRequestLineOut {
  id: number;
  reverse_request_id: number;
  inbound_order_line_id: number;
  purchase_order_line_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  qty: number | string;
}

export interface ReverseRequestListItem {
  id: number;
  no: string;
  request_type: ReverseRequestType;
  status: ReverseRequestStatus;
  sales_order_id: number;
  purchase_order_id: number;
  inbound_order_id: number;
  sales_order_no: string;
  purchase_order_no: string;
  inbound_order_no: string;
  customer_display: string;
  supplier_display: string;
  goods_status: ReverseGoodsStatus;
  supplier_resolution: ReverseSupplierResolution | null;
  line_count: number;
  total_qty: number | string;
  created_at: string;
}

export interface ReverseRequestDetail {
  request: ReverseRequestOut;
  lines: ReverseRequestLineOut[];
}

export interface ReverseRequestListFilters {
  status?: string;
  sales_order_id?: number;
  inbound_order_id?: number;
  q?: string;
  page?: number;
  size?: number;
}

export const reverseRequestApi = {
  list: (p: ReverseRequestListFilters) =>
    api.get<Page<ReverseRequestListItem>>(`/api/v1/reverse-requests${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<ReverseRequestDetail>(`/api/v1/reverse-requests/${id}`),
  create: (body: { inbound_order_id: number; reason: string }) =>
    api.post<ReverseRequestDetail>("/api/v1/reverse-requests", body),
  approve: (id: number, body: { supplier_resolution: ReverseSupplierResolution; review_note?: string | null }) =>
    api.post<ReverseRequestDetail>(`/api/v1/reverse-requests/${id}/approve`, body),
  reject: (id: number, body: { review_note?: string | null }) =>
    api.post<ReverseRequestDetail>(`/api/v1/reverse-requests/${id}/reject`, body),
  complete: (id: number, body: { completion_note?: string | null }) =>
    api.post<ReverseRequestDetail>(`/api/v1/reverse-requests/${id}/complete`, body),
};
