import { api } from "./api";
import type { Page } from "./catalog";
import { qs } from "./qs";

export type PurchaseReturnStatus =
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "RETURNED"
  | "VOIDED";

export type PurchaseReturnKind =
  | "PURCHASE_RETURN"
  | "IN_TRANSIT_CANCELLATION";

export type APCreditMemoStatus = "PENDING_APPROVAL" | "POSTED" | "REJECTED" | "VOIDED";

export const PURCHASE_RETURN_STATUS_META: Record<PurchaseReturnStatus, { label: string; color: string }> = {
  PENDING_APPROVAL: { label: "待审核", color: "warning" },
  APPROVED: { label: "已审核", color: "processing" },
  REJECTED: { label: "已驳回", color: "neutral" },
  RETURNED: { label: "已退货出库", color: "success" },
  VOIDED: { label: "已作废", color: "neutral" },
};

export const AP_CREDIT_MEMO_STATUS_META: Record<APCreditMemoStatus, { label: string; color: string }> = {
  PENDING_APPROVAL: { label: "待财务审核", color: "warning" },
  POSTED: { label: "已过账", color: "success" },
  REJECTED: { label: "已驳回", color: "neutral" },
  VOIDED: { label: "已作废", color: "neutral" },
};

export interface PurchaseReturnableLine {
  inbound_order_line_id: number;
  purchase_order_line_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  language: string;
  received_qty: number | string;
  returned_qty: number | string;
  in_process_return_qty: number | string;
  returnable_qty: number | string;
  remark: string | null;
}

export interface PurchaseReturnLineIn {
  inbound_order_line_id: number;
  qty: number;
  remark?: string | null;
  sort_order?: number;
}

export interface PurchaseReturnCreateBody {
  inbound_order_id: number;
  reason?: string | null;
  lines: PurchaseReturnLineIn[];
}

export interface InTransitCancellationCreateBody {
  inbound_order_id: number;
  reason?: string | null;
}

export interface PurchaseReturnOrderOut {
  id: number;
  no: string;
  inbound_order_id: number;
  purchase_order_id: number;
  sales_order_id: number;
  supplier_id: number;
  currency: string;
  status: PurchaseReturnStatus;
  return_kind: PurchaseReturnKind;
  total_amount: number | string | null;
  reason: string | null;
  submitted_at: string;
  approved_at: string | null;
  approved_by: number | null;
  rejected_at: string | null;
  rejected_by: number | null;
  reject_reason: string | null;
  returned_at: string | null;
  returned_by: number | null;
  return_shipment_reference: string | null;
  return_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface PurchaseReturnLineOut {
  id: number;
  purchase_return_order_id: number;
  inbound_order_line_id: number;
  purchase_order_line_id: number;
  sku_id: number;
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  language: string;
  qty: number | string;
  unit_price: number | string | null;
  line_total: number | string | null;
  sort_order: number;
  remark: string | null;
}

export interface APCreditMemoOut {
  id: number;
  no: string;
  payable_id: number;
  purchase_return_order_id: number;
  supplier_id: number;
  currency: string;
  memo_type: string;
  status: APCreditMemoStatus;
  amount: number | string;
  reason: string | null;
  posted_at: string | null;
  posted_by: number | null;
  rejected_at: string | null;
  rejected_by: number | null;
  reject_reason: string | null;
  created_by: number;
  created_at: string;
}

export interface PurchaseReturnDetail {
  order: PurchaseReturnOrderOut;
  lines: PurchaseReturnLineOut[];
  ap_credit_memo: APCreditMemoOut | null;
}

export interface PurchaseReturnListItem {
  id: number;
  no: string;
  status: PurchaseReturnStatus;
  return_kind: PurchaseReturnKind;
  inbound_order_id: number;
  inbound_order_no: string;
  purchase_order_id: number;
  purchase_order_no: string;
  sales_order_id: number;
  supplier_id: number;
  currency: string;
  total_amount: number | string | null;
  line_count: number;
  total_qty: number | string;
  ap_credit_memo_status: APCreditMemoStatus | null;
  submitted_at: string;
  created_at: string;
}

export const purchaseReturnApi = {
  list: (p: {
    status?: PurchaseReturnStatus;
    inbound_order_id?: number;
    purchase_order_id?: number;
    supplier_id?: number;
    q?: string;
    page?: number;
    size?: number;
  }) => api.get<Page<PurchaseReturnListItem>>(`/api/v1/purchase-returns${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<PurchaseReturnDetail>(`/api/v1/purchase-returns/${id}`),
  returnableLines: (inboundOrderId: number) =>
    api.get<{ items: PurchaseReturnableLine[] }>(
      `/api/v1/purchase-returns/returnable-lines?inbound_order_id=${inboundOrderId}`,
    ),
  create: (body: PurchaseReturnCreateBody) =>
    api.post<PurchaseReturnDetail>("/api/v1/purchase-returns", body),
  createInTransitCancellation: (body: InTransitCancellationCreateBody) =>
    api.post<PurchaseReturnDetail>("/api/v1/purchase-returns/in-transit-cancellations", body),
  approve: (id: number) =>
    api.post<PurchaseReturnOrderOut>(`/api/v1/purchase-returns/${id}/approve`, {}),
  reject: (id: number, reject_reason?: string | null) =>
    api.post<PurchaseReturnOrderOut>(`/api/v1/purchase-returns/${id}/reject`, { reject_reason }),
  confirmReturnShipment: (
    id: number,
    body: { return_shipment_reference?: string | null; return_note?: string | null },
  ) =>
    api.post<PurchaseReturnDetail>(
      `/api/v1/purchase-returns/${id}/confirm-return-shipment`,
      body,
    ),
  confirmInTransitCancellation: (
    id: number,
    body: { cancellation_reference?: string | null; cancellation_note?: string | null },
  ) =>
    api.post<PurchaseReturnDetail>(
      `/api/v1/purchase-returns/${id}/confirm-in-transit-cancellation`,
      body,
    ),
};

export const apCreditMemoApi = {
  list: (p: {
    status?: APCreditMemoStatus;
    supplier_id?: number;
    payable_id?: number;
    purchase_return_order_id?: number;
    page?: number;
    size?: number;
  }) => api.get<Page<APCreditMemoOut>>(`/api/v1/ap-credit-memos${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<APCreditMemoOut>(`/api/v1/ap-credit-memos/${id}`),
  post: (id: number) => api.post<APCreditMemoOut>(`/api/v1/ap-credit-memos/${id}/post`, {}),
  reject: (id: number, reject_reason?: string | null) =>
    api.post<APCreditMemoOut>(`/api/v1/ap-credit-memos/${id}/reject`, { reject_reason }),
  resubmit: (id: number) => api.post<APCreditMemoOut>(`/api/v1/ap-credit-memos/${id}/resubmit`, {}),
};
