// 付款单前端类型 + API。对齐后端 schemas/payment.py + payment_service.build_detail。
// 🔴 整域红线:仅持 payment:read 者可见(付款关联供应商 + 采购付款金额);后端整端点门控,
// 前端只在 /payments 返回 200(RouteGuard 放行)时渲染,不自行判权限藏真值。
// 与收款(receipt.ts)对称,差异:供应商必填、无待认领态、无认领动作、付侧金额恒有值(无 D9)。
import { api } from "./api";
import type { Page } from "./catalog";
import type { AllocType } from "./receipt";
import { qs } from "./qs";

/** 派生状态:未分配 / 部分分配 / 已分配完(后端 derive_payment_status 单一口径,无待认领)。 */
export type PaymentStatus = "UNALLOCATED" | "PARTIALLY_ALLOCATED" | "FULLY_ALLOCATED";

export type PaymentStatusFilter = PaymentStatus | "VOIDED";

/** 派生状态徽标映射(单一源头在后端;色沿用平台语义令牌,不写色值)。 */
export const PAYMENT_STATUS_META: Record<PaymentStatus, { label: string; color: string }> = {
  UNALLOCATED: { label: "未分配", color: "processing" },
  PARTIALLY_ALLOCATED: { label: "部分分配", color: "processing" },
  FULLY_ALLOCATED: { label: "已分配完", color: "success" },
};

export interface PaymentListItem {
  id: number;
  payment_no: string;
  supplier_id: number;
  supplier_display: string;
  currency: string;
  amount: number;
  amount_allocated: number;
  amount_unallocated: number;
  paid_at: string;
  status: PaymentStatus;
  voided_at: string | null;
  created_at: string;
}

export interface PaymentHead {
  id: number;
  payment_no: string;
  supplier_id: number;
  supplier_display: string;
  account_info: string | null;
  currency: string;
  amount: number;
  amount_allocated: number;
  amount_unallocated: number;
  paid_at: string;
  note: string | null;
  status: PaymentStatus;
  voided_at: string | null;
  void_reason: string | null;
  created_at: string;
  updated_at: string;
}

/** 活动核销记录行。account_no = 冲的应付展示号(入库单号)。付侧无 D9,amount 恒有值。 */
export interface PaymentAllocationRow {
  id: number;
  payable_id: number;
  account_no: string;
  amount: number;
  alloc_type: AllocType;
  created_at: string;
}

export interface PaymentDetail {
  payment: PaymentHead;
  allocations: PaymentAllocationRow[];
}

/** 登记付款入参(amount/currency/paid_at/supplier_id 必填,无待认领)。 */
export interface PaymentCreateBody {
  amount: string;
  currency: string;
  paid_at: string;
  supplier_id: number;
  account_info?: string | null;
  note?: string | null;
}

export interface PaymentListFilters {
  supplier_id?: number;
  currency?: string;
  status?: PaymentStatusFilter;
  /** 单号 / 供应商名 模糊搜索。 */
  q?: string;
  page?: number;
  size?: number;
}

export const paymentApi = {
  list: (p: PaymentListFilters) =>
    api.get<Page<PaymentListItem>>(`/api/v1/payments${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<PaymentDetail>(`/api/v1/payments/${id}`),
  create: (b: PaymentCreateBody) => api.post<PaymentDetail>("/api/v1/payments", b),
  void: (id: number, void_reason?: string | null) =>
    api.post<PaymentDetail>(`/api/v1/payments/${id}/void`, { void_reason: void_reason ?? null }),
  /** 人工核销:只传 account_id(=payable_id),金额后端自动取满 min。 */
  allocate: (id: number, account_id: number) =>
    api.post<PaymentDetail>(`/api/v1/payments/${id}/allocations`, { account_id }),
  /** 反核销:reverse_reason 走 query,后端返回刷新后的付款详情。 */
  reverseAllocation: (allocId: number, reverse_reason?: string | null) =>
    api.del<PaymentDetail>(
      `/api/v1/payment-allocations/${allocId}${qs({ reverse_reason: reverse_reason || undefined })}`,
    ),
};
