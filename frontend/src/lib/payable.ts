// 应付款前端类型 + API。对齐后端 schemas/payable.py。
// 🔴 整域红线:仅持 payable:read 者可见;后端整端点/整块门控。前端不自行判权限藏真值,
// 只在响应含 payable 键 / /payables 返回 200 时渲染。
import { api } from "./api";
import type { Page } from "./catalog";
import { formatMoney } from "./format";
import { qs } from "./qs";

/** 派生状态:未付 / 部分付 / 已付清(后端由 amount_* 单一口径派生)。 */
export type PayableStatus = "UNPAID" | "PARTIALLY_PAID" | "PAID";

/** 入库详情内嵌 payable 块(有活动应付且持 payable:read 时下发)。 */
export interface PayableOut {
  id: number;
  inbound_order_id: number;
  purchase_order_id: number;
  supplier_id: number;
  currency: string;
  amount_original: number | string;
  amount_credited: number | string;
  amount_allocated: number | string;
  amount_outstanding: number | string;
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
  amount_credited: number | string;
  amount_allocated: number | string;
  amount_outstanding: number | string;
  status: PayableStatus;
  due_at: string | null;
  created_at: string;
  /** 该供应商名下有未分配付款(可一键核销此账)。 */
  counterparty_has_unallocated: boolean;
}

/** 应付详情内活动核销记录行:哪笔付款、冲了多少、何时。 */
export interface PayableAllocationRow {
  id: number;
  payment_id: number;
  payment_no: string;
  amount: number;
  alloc_type: "AUTO" | "MANUAL";
  created_at: string;
}

/** 应付详情(账头 + 活动核销记录),GET /payables/{id}。🔴红线。 */
export interface PayableDetail {
  id: number;
  inbound_order_id: number;
  inbound_order_no: string;
  purchase_order_id: number;
  supplier_id: number;
  supplier_display: string | null;
  currency: string;
  amount_original: number;
  amount_credited: number;
  amount_allocated: number;
  amount_outstanding: number;
  status: PayableStatus;
  due_at: string | null;
  created_at: string;
  allocations: PayableAllocationRow[];
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
  get: (id: number) => api.get<PayableDetail>(`/api/v1/payables/${id}`),
};
