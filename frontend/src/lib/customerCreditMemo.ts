import { api } from "./api";
import type { Page } from "./catalog";
import { qs } from "./qs";

export type CustomerCreditMemoStatus = "PENDING_APPROVAL" | "POSTED" | "REJECTED" | "VOIDED";

export const CUSTOMER_CREDIT_MEMO_STATUS_META: Record<
  CustomerCreditMemoStatus,
  { label: string; color: string }
> = {
  PENDING_APPROVAL: { label: "待财务审核", color: "warning" },
  POSTED: { label: "已过账", color: "success" },
  REJECTED: { label: "已驳回", color: "neutral" },
  VOIDED: { label: "已作废", color: "neutral" },
};

export interface CustomerCreditMemoOut {
  id: number;
  no: string;
  inventory_disposition_order_id: number;
  sales_order_id: number;
  customer_id: number;
  currency: "CNY";
  memo_type: string;
  status: CustomerCreditMemoStatus;
  amount: number | string;
  amount_allocated: number | string;
  amount_unallocated: number | string;
  reason: string | null;
  posted_at: string | null;
  posted_by: number | null;
  rejected_at: string | null;
  rejected_by: number | null;
  reject_reason: string | null;
  resubmitted_from_id: number | null;
  voided_at: string | null;
  voided_by: number | null;
  void_reason: string | null;
  created_by: number;
  created_at: string;
}

export interface CustomerCreditMemoCreateBody {
  inventory_disposition_order_id: number;
  amount: number | string;
  currency?: "CNY";
  reason?: string | null;
}

export interface CustomerCreditAllocationOut {
  id: number;
  customer_credit_memo_id: number;
  receivable_id: number;
  account_id: number;
  account_no: string;
  outbound_order_id: number;
  amount: number | string;
  alloc_type: "AUTO" | "MANUAL";
  source_type: "CUSTOMER_CREDIT_MEMO";
  idempotency_key: string;
  created_by: number;
  created_at: string;
  status: "ACTIVE" | "REVERSED";
  reversed_at: string | null;
  reversed_by: number | null;
  reverse_reason: string | null;
}

export interface CustomerCreditMemoDetailOut {
  memo: CustomerCreditMemoOut;
  allocations: CustomerCreditAllocationOut[];
}

export interface CustomerCreditMemoResubmitBody {
  amount: number | string;
  reason?: string | null;
}

export const customerCreditMemoApi = {
  list: (p: {
    status?: CustomerCreditMemoStatus;
    customer_id?: number;
    sales_order_id?: number;
    inventory_disposition_order_id?: number;
    page?: number;
    size?: number;
  }) => api.get<Page<CustomerCreditMemoOut>>(`/api/v1/customer-credit-memos${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<CustomerCreditMemoDetailOut>(`/api/v1/customer-credit-memos/${id}`),
  create: (body: CustomerCreditMemoCreateBody) =>
    api.post<CustomerCreditMemoOut>("/api/v1/customer-credit-memos", body),
  post: (id: number) =>
    api.post<CustomerCreditMemoOut>(`/api/v1/customer-credit-memos/${id}/post`, {}),
  reject: (id: number, reject_reason: string) =>
    api.post<CustomerCreditMemoOut>(`/api/v1/customer-credit-memos/${id}/reject`, { reject_reason }),
  resubmit: (id: number, body: CustomerCreditMemoResubmitBody) =>
    api.post<CustomerCreditMemoOut>(`/api/v1/customer-credit-memos/${id}/resubmit`, body),
  allocate: (id: number, body: { account_id: number; amount?: number | string; idempotency_key: string }) =>
    api.post<{ allocation_id: number }>(`/api/v1/customer-credit-memos/${id}/allocations`, body),
  reverseAllocation: (allocationId: number, reverse_reason: string) =>
    api.post<{ allocation_id: number }>(
      `/api/v1/customer-credit-memos/allocations/${allocationId}/reverse`,
      { reverse_reason },
    ),
  void: (id: number, void_reason: string) =>
    api.post<CustomerCreditMemoOut>(`/api/v1/customer-credit-memos/${id}/void`, { void_reason }),
};
