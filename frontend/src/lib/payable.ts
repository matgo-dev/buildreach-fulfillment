// 应付款前端类型 + API。对齐后端 schemas/payable.py。
// 🔴 整域红线:仅持 payable:read 者可见;后端整端点/整块门控。前端不自行判权限藏真值,
// 只在响应含 payable 键 / /payables 返回 200 时渲染。
import { api } from "./api";
import type { Page } from "./catalog";
import { formatMoney } from "./format";

/** 派生状态:未付 / 部分付 / 已付清(后端由 amount_* 单一口径派生)。 */
export type PayableStatus = "UNPAID" | "PARTIALLY_PAID" | "PAID";

/** 入库详情内嵌 payable 块(仅 RECEIVED 且持 payable:read 时下发)。 */
export interface PayableOut {
  id: number;
  inbound_order_id: number;
  purchase_order_id: number;
  supplier_id: number;
  currency: string;
  amount_original: number | string;
  amount_allocated: number | string;
  balance: number | string;
  status: PayableStatus;
  due_at: string | null;
  created_at: string;
}

export interface PayableListItem {
  id: number;
  inbound_order_id: number;
  inbound_order_no: string;
  purchase_order_id: number;
  purchase_order_no: string;
  supplier_id: number;
  supplier_display: string;
  currency: string;
  amount_original: number | string;
  amount_allocated: number | string;
  balance: number | string;
  status: PayableStatus;
  due_at: string | null;
  created_at: string;
}

/** 派生状态徽标映射。 */
export const PAYABLE_STATUS_META: Record<PayableStatus, { label: string; color: string }> = {
  UNPAID: { label: "未付", color: "warning" },
  PARTIALLY_PAID: { label: "部分付", color: "processing" },
  PAID: { label: "已付清", color: "success" },
};

/** 金额格式化(应付域内均为真值,不涉红线脱敏)。 */
export function formatAmount(v: number | string): string {
  return formatMoney(v);
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface PayableListFilters {
  supplier_id?: number;
  currency?: string;
  /** 派生状态筛选(服务端谓词镜像 derive_payable_status)。 */
  status?: PayableStatus;
  /** 入库单号 / 采购单号 / 供应商名 模糊搜索。 */
  q?: string;
  page?: number;
  size?: number;
}

export const payableApi = {
  list: (p: PayableListFilters) =>
    api.get<Page<PayableListItem>>(`/api/v1/payables${qs(p as Record<string, unknown>)}`),
};
