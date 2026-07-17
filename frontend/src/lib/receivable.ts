// 应收款前端类型 + API。对齐后端 schemas/receivable.py(镜像 payable)。
// 🔴 整域红线:仅持 receivable:read 者可见(应收含客户售价);后端整端点门控。
// 应收 = 发货(我方履约完成),每出库单一张,与应付(每入库单一张)完全对称。
import { api } from "./api";
import type { Page } from "./catalog";

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
}

/** 派生状态徽标映射(沿用应付三色:warning / processing / success)。 */
export const RECEIVABLE_STATUS_META: Record<ReceivableStatus, { label: string; color: string }> = {
  UNPAID: { label: "未收", color: "warning" },
  PARTIALLY_PAID: { label: "部分收", color: "processing" },
  PAID: { label: "已收清", color: "success" },
};

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

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
};
