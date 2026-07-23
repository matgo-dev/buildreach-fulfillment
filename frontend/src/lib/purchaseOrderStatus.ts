// 采购单状态机的前端镜像 —— 唯一权威源头是 backend db/models/purchase_order.py
// (PURCHASE_ORDER_TRANSITIONS / EDITABLE)。此处只映射 UI 呈现,
// 不重复业务规则:后端才是硬约束,前端隐藏按钮只是 UX,越权调用仍被后端拦。
import type { PurchaseOrderStatus, PurchaseProgress } from "@/lib/purchaseOrder";

/** 三态:草稿(可编辑)/ 已确认(冻结)/ 已取消(终态)。 */
export const PURCHASE_ORDER_STATUS_META: Record<PurchaseOrderStatus, { label: string; color: string }> = {
  DRAFT: { label: "草稿", color: "warning" },
  CONFIRMED: { label: "已确认", color: "success" },
  CANCELLED: { label: "已取消", color: "default" },
};

// 镜像转移矩阵:DRAFT→{CONFIRMED,CANCELLED} / CONFIRMED→{CANCELLED} / CANCELLED→{}。
const PURCHASE_ORDER_TRANSITIONS: Record<PurchaseOrderStatus, PurchaseOrderStatus[]> = {
  DRAFT: ["CONFIRMED", "CANCELLED"],
  CONFIRMED: ["CANCELLED"],
  CANCELLED: [],
};

/** 镜像 EDITABLE:仅草稿可改。无硬删——退役走取消。 */
export const purchaseOrderEditable = (s: PurchaseOrderStatus): boolean => s === "DRAFT";

/** 详情页状态门禁动作(镜像转移矩阵)。 */
export const purchaseOrderConfirmable = (s: PurchaseOrderStatus): boolean =>
  PURCHASE_ORDER_TRANSITIONS[s].includes("CONFIRMED");
export const purchaseOrderCancellable = (s: PurchaseOrderStatus): boolean =>
  PURCHASE_ORDER_TRANSITIONS[s].includes("CANCELLED");

/**
 * 采购进度映射(销售单相对采购覆盖度)。经 ProgressCell 渲染成分级状态标记(描边 chip + 方块图标),
 * 与「单据状态」实心 pill 换形区分;三态由 color 判级(default 未开始 / processing 进行中 / success 完成)。
 */
export const PURCHASE_PROGRESS_META: Record<PurchaseProgress, { label: string; color: string }> = {
  NOT_ORDERED: { label: "未下单", color: "default" },
  PARTIALLY_ORDERED: { label: "部分下单", color: "processing" },
  FULLY_ORDERED: { label: "已全部下单", color: "success" },
};
