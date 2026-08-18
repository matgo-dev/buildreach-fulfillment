import { api } from "./api";

export type InventoryDispositionStatus =
  | "PENDING_RECEIPT"
  | "HELD"
  | "CLOSED_WITHOUT_RECEIPT"
  | "VOIDED";
export type InventoryDispositionReceiptHandling =
  | "CLOSE_WITHOUT_RECEIPT"
  | "RECEIVE_TO_DISPOSITION";

export const INVENTORY_DISPOSITION_STATUS_META: Record<
  InventoryDispositionStatus,
  { label: string; color: string }
> = {
  PENDING_RECEIPT: { label: "待收货", color: "warning" },
  HELD: { label: "已待处置", color: "success" },
  CLOSED_WITHOUT_RECEIPT: { label: "关闭未收货", color: "default" },
  VOIDED: { label: "已作废", color: "neutral" },
};

export const INVENTORY_DISPOSITION_RECEIPT_HANDLING_META: Record<
  InventoryDispositionReceiptHandling,
  string
> = {
  CLOSE_WITHOUT_RECEIPT: "终止入仓",
  RECEIVE_TO_DISPOSITION: "到仓后待处置",
};

export interface InventoryDispositionCreateBody {
  inbound_order_id: number;
  receipt_handling: InventoryDispositionReceiptHandling;
  reason?: string | null;
}

export interface InventoryDispositionOut {
  id: number;
  no: string;
  inbound_order_id: number;
  purchase_order_id: number;
  sales_order_id: number;
  payable_id: number;
  purchase_currency: string;
  status: InventoryDispositionStatus;
  receipt_handling: InventoryDispositionReceiptHandling;
  supplier_payable_amount: number | string | null;
  reason: string | null;
  held_at: string | null;
  held_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryDispositionDetail {
  order: InventoryDispositionOut;
  lines: unknown[];
}

export const inventoryDispositionApi = {
  create: (body: InventoryDispositionCreateBody) =>
    api.post<InventoryDispositionDetail>("/api/v1/inventory-dispositions", body),
  byInbound: (inboundOrderId: number) =>
    api.get<InventoryDispositionDetail | null>(
      `/api/v1/inventory-dispositions/by-inbound/${inboundOrderId}`,
    ),
};
