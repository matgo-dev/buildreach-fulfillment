// 报关派生状态的前端镜像 —— 权威源头是 backend 的 CustomsStatus。
// 此处只映射 UI 呈现(中文 label = 界面语言展示层,code 在后端),不重复业务规则。
import type { CustomsStatus } from "@/lib/shipment";

/**
 * 报关状态徽标元数据(供 StatusTag)。色遵 DESIGN.md §1.3 语义名:
 * 未报关 = default(未开始)/ 已申报 = processing(进行中)/ 已放行 = success(完成)。
 */
export const CUSTOMS_STATUS_META: Record<CustomsStatus, { label: string; color: string }> = {
  NONE: { label: "未报关", color: "default" },
  DECLARED: { label: "已申报", color: "processing" },
  RELEASED: { label: "已放行", color: "success" },
};

/** 报关状态下拉筛选项(全部 + 三态,单一源头 CUSTOMS_STATUS_META)。 */
export const CUSTOMS_FILTER_OPTIONS: { label: string; value: string }[] = [
  { label: "全部报关状态", value: "" },
  { label: CUSTOMS_STATUS_META.NONE.label, value: "NONE" },
  { label: CUSTOMS_STATUS_META.DECLARED.label, value: "DECLARED" },
  { label: CUSTOMS_STATUS_META.RELEASED.label, value: "RELEASED" },
];
