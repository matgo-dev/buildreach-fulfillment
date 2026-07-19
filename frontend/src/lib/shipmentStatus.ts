// 发运柜状态机的前端镜像 —— 唯一权威源头是 backend db/models/shipment_order.py
// (SHIPMENT_ORDER_TRANSITIONS)。此处只映射 UI 呈现,不重复业务规则。
import type { ShipmentStatus } from "@/lib/shipment";

/** 柜型 code(受控值域框架:应用层枚举,不落 DB CHECK;消费者仅表单校验)。 */
export const CONTAINER_TYPE_OPTIONS = [
  { value: "20GP", label: "20GP" },
  { value: "40GP", label: "40GP" },
  { value: "40HQ", label: "40HQ" },
  { value: "45HQ", label: "45HQ" },
] as const;

/**
 * 两态:组柜中(OPEN,可编辑/可加出库单)/ 已取消(终态)。
 * 色值遵契约 §4:组柜中=蓝 / 已取消=中性。发运步将扩展 OPEN→LOADED→…。
 */
export const SHIPMENT_STATUS_META: Record<ShipmentStatus, { label: string; color: string }> = {
  OPEN: { label: "组柜中", color: "processing" },
  CANCELLED: { label: "已取消", color: "default" },
};

// 镜像转移矩阵:OPEN→{CANCELLED} / CANCELLED→{}(发运步扩展 OPEN→LOADED→…)。
const SHIPMENT_ORDER_TRANSITIONS: Record<ShipmentStatus, ShipmentStatus[]> = {
  OPEN: ["CANCELLED"],
  CANCELLED: [],
};

/** 镜像可编辑集:仅组柜中可改柜信息 / 加出库单。 */
export const shipmentEditable = (s: ShipmentStatus): boolean => s === "OPEN";

/** 取消柜 = OPEN→CANCELLED(后端守卫:柜下无活动出库单,否则 42001)。 */
export const shipmentCancellable = (s: ShipmentStatus): boolean =>
  SHIPMENT_ORDER_TRANSITIONS[s].includes("CANCELLED");
