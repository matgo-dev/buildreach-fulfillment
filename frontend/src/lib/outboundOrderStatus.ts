// 出库单状态机的前端镜像 —— 唯一权威源头是 backend db/models/outbound_order.py
// (OUTBOUND_ORDER_TRANSITIONS / 可编辑集)。此处只映射 UI 呈现,不重复业务规则:
// 后端才是硬约束,前端隐藏按钮只是 UX,越权调用仍被后端拦。
import type { OutboundOrderStatus } from "@/lib/outboundOrder";

/**
 * 三态:草稿(可编辑,不扣库存)/ 已出库(确认出库,唯一扣减事件,生成应收)/ 已取消(终态)。
 * 色遵 DESIGN.md §1.3(状态色唯一源头):草稿=warning 琥珀(未生效)/ 已出库=success 青(正向完成)/
 * 已取消=default 灰(中性终态,与「停用」同档;红只留给危险动作,不给静止状态)。
 */
export const OUTBOUND_ORDER_STATUS_META: Record<
  OutboundOrderStatus,
  { label: string; color: string }
> = {
  DRAFT: { label: "草稿", color: "warning" },
  ISSUED: { label: "已出库", color: "success" },
  CANCELLED: { label: "已取消", color: "default" },
};

// 镜像转移矩阵:DRAFT→{ISSUED,CANCELLED} / ISSUED→{} / CANCELLED→{}。
const OUTBOUND_ORDER_TRANSITIONS: Record<OutboundOrderStatus, OutboundOrderStatus[]> = {
  DRAFT: ["ISSUED", "CANCELLED"],
  ISSUED: [],
  CANCELLED: [],
};

/** 镜像可编辑集:仅草稿可整单重写。 */
export const outboundOrderEditable = (s: OutboundOrderStatus): boolean => s === "DRAFT";

/** 详情页状态门禁动作(镜像转移矩阵)。 */
/** 确认出库 = DRAFT→ISSUED。 */
export const outboundOrderConfirmable = (s: OutboundOrderStatus): boolean =>
  OUTBOUND_ORDER_TRANSITIONS[s].includes("ISSUED");
/** 取消 = DRAFT→CANCELLED。 */
export const outboundOrderCancellable = (s: OutboundOrderStatus): boolean =>
  OUTBOUND_ORDER_TRANSITIONS[s].includes("CANCELLED");
