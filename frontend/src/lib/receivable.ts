// 应收款前端类型 + API。对齐后端 schemas/receivable.py(镜像 payable)。
// 🔴 整域红线:仅持 receivable:read 者可见(应收含客户售价);后端整端点门控。
// 应收 = 发货(我方履约完成),每出库单一张,与应付(每入库单一张)完全对称。
import { api } from "./api";
import type { Page } from "./catalog";
import { qs } from "./qs";

/** 派生状态:未收 / 部分收 / 已收清(后端由 amount_* 单一口径派生,沿用应付三色)。 */
export type ReceivableStatus = "UNPAID" | "PARTIALLY_PAID" | "PAID";

export interface ReceivableListItem {
  id: number;
  outbound_order_id: number;
  outbound_order_no: string;
  sales_order_id: number;
  sales_order_no: string;
  customer_id: number;
  customer_display: string;
  currency: string;
  amount_original: number | string;
  amount_allocated: number | string;
  balance: number | string;
  status: ReceivableStatus;
  due_at: string | null;
  created_at: string;
  /** 该客户名下有未分配收款余额(可一键用余额核销此账)。 */
  counterparty_has_unallocated: boolean;
}

/** 应收详情内活动核销记录行:哪笔收款、冲了多少、何时。 */
export interface ReceivableAllocationRow {
  id: number;
  receipt_id: number;
  receipt_no: string;
  amount: number;
  alloc_type: "AUTO" | "MANUAL";
  created_at: string;
}

/** 应收详情(账头 + 活动核销记录),GET /receivables/{id}。 */
export interface ReceivableDetail {
  id: number;
  outbound_order_id: number;
  outbound_order_no: string;
  sales_order_id: number;
  customer_id: number;
  customer_display: string | null;
  currency: string;
  amount_original: number;
  amount_allocated: number;
  balance: number;
  status: ReceivableStatus;
  due_at: string | null;
  created_at: string;
  allocations: ReceivableAllocationRow[];
}

/** 派生状态徽标映射(沿用应付三色:warning / processing / success)。 */
export const RECEIVABLE_STATUS_META: Record<ReceivableStatus, { label: string; color: string }> = {
  UNPAID: { label: "未收", color: "warning" },
  PARTIALLY_PAID: { label: "部分收", color: "processing" },
  PAID: { label: "已收清", color: "success" },
};

export interface ReceivableListFilters {
  customer_id?: number;
  currency?: string;
  /** 派生状态筛选(服务端谓词镜像 derive_receivable_status)。 */
  status?: ReceivableStatus;
  /** 出库单号 / 销售单号 / 客户名 模糊搜索。 */
  q?: string;
  page?: number;
  size?: number;
}

export const receivableApi = {
  list: (p: ReceivableListFilters) =>
    api.get<Page<ReceivableListItem>>(`/api/v1/receivables${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<ReceivableDetail>(`/api/v1/receivables/${id}`),
};
