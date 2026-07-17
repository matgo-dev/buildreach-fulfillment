// 销售单状态机的前端镜像 —— 唯一权威源头是 backend db/models/sales_order.py
// (SALES_ORDER_TRANSITIONS)。此处只映射 UI 呈现,不重复业务规则。
import type { SalesOrderStatus } from "@/lib/salesOrder";

export const SALES_ORDER_STATUS_META: Record<SalesOrderStatus, { label: string; color: string }> = {
  CONFIRMED: { label: "已确认", color: "success" },
  CANCELLED: { label: "已取消", color: "default" },
};

/** 可取消 = 有 CONFIRMED→CANCELLED 出边(镜像 SALES_ORDER_TRANSITIONS,不另立规则)。 */
export const salesOrderCancellable = (s: SalesOrderStatus): boolean => s === "CONFIRMED";
