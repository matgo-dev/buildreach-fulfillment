// 收款单前端类型 + API。对齐后端 schemas/receipt.py + receipt_service.build_detail。
// 收款 = 客户售价侧(同 receivable:read 域,非红线);核销记录里的应收额按 D9 门控:
// 无 receivable:read 者后端脱敏为 null(amount=null),前端显「—」,不自行判权限。
// 收款与付款(payment.ts)对称,差异:收款有「待认领」态 + 认领动作。
import { api } from "./api";
import type { Page } from "./catalog";

/** 派生状态:待认领 / 未分配 / 部分分配 / 已分配完(后端 derive_receipt_status 单一口径)。
 *  作废态不进此映射,靠单头 voided_at 单独呈现「已作废」。 */
export type ReceiptStatus = "UNCLAIMED" | "UNALLOCATED" | "PARTIALLY_ALLOCATED" | "FULLY_ALLOCATED";

/** 列表筛选可多一个 VOIDED(显式查作废行);单头 status 字段本身不含 VOIDED。 */
export type ReceiptStatusFilter = ReceiptStatus | "VOIDED";

/** 核销类型:AUTO=登记/认领时自动核销;MANUAL=人工指定应收核销。 */
export type AllocType = "AUTO" | "MANUAL";

/** 派生状态徽标映射(单一源头在后端;色沿用平台语义令牌,不写色值)。 */
export const RECEIPT_STATUS_META: Record<ReceiptStatus, { label: string; color: string }> = {
  UNCLAIMED: { label: "待认领", color: "warning" },
  UNALLOCATED: { label: "未分配", color: "processing" },
  PARTIALLY_ALLOCATED: { label: "部分分配", color: "processing" },
  FULLY_ALLOCATED: { label: "已分配完", color: "success" },
};

export interface ReceiptListItem {
  id: number;
  receipt_no: string;
  customer_id: number | null;
  /** 空 = 待认领(后端未回填客户)。 */
  customer_display: string | null;
  currency: string;
  amount: number;
  amount_allocated: number;
  amount_unallocated: number;
  received_at: string;
  status: ReceiptStatus;
  voided_at: string | null;
  created_at: string;
}

/** 单头(详情/登记/认领/核销/作废/反核销 各操作统一返回 { receipt, allocations })。 */
export interface ReceiptHead {
  id: number;
  receipt_no: string;
  customer_id: number | null;
  customer_display: string | null;
  account_info: string | null;
  currency: string;
  amount: number;
  amount_allocated: number;
  amount_unallocated: number;
  received_at: string;
  note: string | null;
  status: ReceiptStatus;
  voided_at: string | null;
  void_reason: string | null;
  created_at: string;
  updated_at: string;
}

/** 活动核销记录行。account_no = 冲的应收展示号(出库单号);amount=null 为 D9 脱敏。 */
export interface ReceiptAllocationRow {
  id: number;
  receivable_id: number;
  account_no: string;
  amount: number | null;
  alloc_type: AllocType;
  created_at: string;
}

export interface ReceiptDetail {
  receipt: ReceiptHead;
  allocations: ReceiptAllocationRow[];
}

/** 登记收款入参(amount/currency/received_at 必填;customer_id 空 = 待认领)。 */
export interface ReceiptCreateBody {
  amount: string;
  currency: string;
  received_at: string;
  customer_id?: number | null;
  account_info?: string | null;
  note?: string | null;
}

export interface ReceiptListFilters {
  customer_id?: number;
  currency?: string;
  status?: ReceiptStatusFilter;
  /** 单号 / 客户名 模糊搜索。 */
  q?: string;
  page?: number;
  size?: number;
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const receiptApi = {
  list: (p: ReceiptListFilters) =>
    api.get<Page<ReceiptListItem>>(`/api/v1/receipts${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<ReceiptDetail>(`/api/v1/receipts/${id}`),
  create: (b: ReceiptCreateBody) => api.post<ReceiptDetail>("/api/v1/receipts", b),
  claim: (id: number, customer_id: number) =>
    api.post<ReceiptDetail>(`/api/v1/receipts/${id}/claim`, { customer_id }),
  void: (id: number, void_reason?: string | null) =>
    api.post<ReceiptDetail>(`/api/v1/receipts/${id}/void`, { void_reason: void_reason ?? null }),
  /** 人工核销:只传 account_id(=receivable_id),金额后端自动取满 min。 */
  allocate: (id: number, account_id: number) =>
    api.post<ReceiptDetail>(`/api/v1/receipts/${id}/allocations`, { account_id }),
  /** 反核销:reverse_reason 走 query(DELETE body 公网不可靠),后端返回刷新后的收款详情。 */
  reverseAllocation: (allocId: number, reverse_reason?: string | null) =>
    api.del<ReceiptDetail>(
      `/api/v1/receipt-allocations/${allocId}${qs({ reverse_reason: reverse_reason || undefined })}`,
    ),
};
