// 物流里程碑的前端镜像 —— 权威源头是 backend db/models/shipment_event.py 的 LogisticsMilestone。
// 此处只映射 UI 呈现(中文 label = 界面语言展示层,code 在后端),不重复业务规则。
import type { LogisticsEventType, LogisticsMilestone } from "@/lib/shipment";

/**
 * 当前物流状态徽标元数据(供 StatusTag)。色遵 DESIGN.md §1.3 语义名:
 * 已离港/中转 = processing(在途·进行中)/ 到港 = success(完成)。
 */
export const LOGISTICS_MILESTONE_META: Record<LogisticsMilestone, { label: string; color: string }> = {
  DEPARTED: { label: "已离港", color: "processing" },
  TRANSSHIPMENT: { label: "中转", color: "processing" },
  ARRIVED: { label: "到港", color: "success" },
};

/** 可录入事件类型(镜像 model LogisticsMilestone.EVENT_TYPES;已离港是派生态,不可录)。 */
export const LOGISTICS_EVENT_TYPE_OPTIONS: { value: LogisticsEventType; label: string }[] = [
  { value: "TRANSSHIPMENT", label: "中转" },
  { value: "ARRIVED", label: "到港" },
];

/** 全流程展示骨架顺序(镜像 model DISPLAY_ORDER):已离港 → 中转 → 到港。 */
export const LOGISTICS_DISPLAY_ORDER: LogisticsMilestone[] = ["DEPARTED", "TRANSSHIPMENT", "ARRIVED"];
