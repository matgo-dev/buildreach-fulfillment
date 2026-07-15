// 销售单状态机的前端镜像 —— 唯一权威源头是 backend db/models/sales_order.py
// (SALES_ORDER_TRANSITIONS)。此处只映射 UI 呈现,不重复业务规则。
// 本增量销售单只建初始态 CONFIRMED;完整状态机留给转采购增量。
import type { SalesOrderStatus } from "@/lib/salesOrder";

export const SALES_ORDER_STATUS_META: Record<SalesOrderStatus, { label: string; color: string }> = {
  CONFIRMED: { label: "已确认", color: "success" },
};
