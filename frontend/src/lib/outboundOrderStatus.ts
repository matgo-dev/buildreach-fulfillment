// 出库单状态机的前端镜像 —— 唯一权威源头是 backend db/models/outbound_order.py
// (OUTBOUND_ORDER_TRANSITIONS / 可编辑集)。此处只映射 UI 呈现,不重复业务规则:
// 后端才是硬约束,前端隐藏按钮只是 UX,越权调用仍被后端拦。
import type { OutboundOrderStatus } from "@/lib/outboundOrder";

/**
 * 三态:草稿(可编辑,不扣库存)/ 已出库(确认出库,唯一扣减事件,生成应收)/ 已取消(终态)。
 * 色值遵契约 §4:草稿=灰 / 已出库=绿 / 已取消=中性(草稿与取消同为中性灰,靠文字区分)。
 */
export const OUTBOUND_ORDER_STATUS_META: Record<
  OutboundOrderStatus,
  { label: string; color: string }
> = {
  DRAFT: { label: "草稿", color: "default" },
  ISSUED: { label: "已出库", color: "success" },
  CANCELLED: { label: "已取消", color: "default" },
};

// 镜像转移矩阵:DRAFT→{ISSUED,CANCELLED} / ISSUED→{DRAFT}(撤销出库) / CANCELLED→{}。
const OUTBOUND_ORDER_TRANSITIONS: Record<OutboundOrderStatus, OutboundOrderStatus[]> = {
  DRAFT: ["ISSUED", "CANCELLED"],
  ISSUED: ["DRAFT"],
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
/** 撤销出库 = ISSUED→DRAFT。 */
export const outboundOrderRevertable = (s: OutboundOrderStatus): boolean =>
  OUTBOUND_ORDER_TRANSITIONS[s].includes("DRAFT");
