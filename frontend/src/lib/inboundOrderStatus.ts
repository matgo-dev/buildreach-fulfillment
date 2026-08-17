// 入库单状态机的前端镜像 —— 唯一权威源头是 backend db/models/inbound_order.py
// (INBOUND_ORDER_TRANSITIONS / 可编辑集)。此处只映射 UI 呈现,不重复业务规则:
// 后端才是硬约束,前端隐藏按钮只是 UX,越权调用仍被后端拦。
import type { InboundOrderStatus } from "@/lib/inboundOrder";
import type { ReceiptProgress } from "@/lib/purchaseOrder";

/** 三态:在途(待确认入库)/ 已入库(库存已形成)/ 已作废(历史保留态)。 */
export const INBOUND_ORDER_STATUS_META: Record<InboundOrderStatus, { label: string; color: string }> = {
  IN_TRANSIT: { label: "在途", color: "processing" },
  RECEIVED: { label: "已入库", color: "success" },
  CANCELLED: { label: "已作废", color: "default" },
};

// 镜像转移矩阵:IN_TRANSIT→{RECEIVED} / RECEIVED→{IN_TRANSIT}(撤销入库) / CANCELLED→{}。
const INBOUND_ORDER_TRANSITIONS: Record<InboundOrderStatus, InboundOrderStatus[]> = {
  IN_TRANSIT: ["RECEIVED"],
  RECEIVED: ["IN_TRANSIT"],
  CANCELLED: [],
};

/** 创建入库单即产生应付,当前不再提供裸编辑入口。 */
export const inboundOrderEditable = (_s: InboundOrderStatus): boolean => false;

/** 详情页状态门禁动作(镜像转移矩阵)。 */
export const inboundOrderReceivable = (s: InboundOrderStatus): boolean =>
  INBOUND_ORDER_TRANSITIONS[s].includes("RECEIVED");
export const inboundOrderCancellable = (_s: InboundOrderStatus): boolean => false;
/** 撤销入库 = RECEIVED→IN_TRANSIT。 */
export const inboundOrderUnreceivable = (s: InboundOrderStatus): boolean =>
  INBOUND_ORDER_TRANSITIONS[s].includes("IN_TRANSIT");

/**
 * 收货进度映射(PO 相对入库覆盖度)。经 ProgressCell 复用 StatusTag 视觉规则:
 * 状态圆点 + 精确语义色,与单据状态保持同一套徽标样式。
 */
export const RECEIPT_PROGRESS_META: Record<ReceiptProgress, { label: string; color: string }> = {
  NOT_RECEIVED: { label: "未入库", color: "default" },
  PARTIALLY_RECEIVED: { label: "部分入库", color: "processing" },
  FULLY_RECEIVED: { label: "已全部入库", color: "success" },
};
