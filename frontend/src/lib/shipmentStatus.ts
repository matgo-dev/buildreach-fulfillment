// 发运柜状态机 + 字段门禁的前端镜像 —— 唯一权威源头是 backend db/models/shipment_order.py
// (SHIPMENT_ORDER_TRANSITIONS / SHIPMENT_EDITABLE_FIELDS_BY_STATUS)。此处只映射 UI 呈现,
// 不重复业务规则:后端才是硬约束,前端隐藏/禁用按钮只是 UX,越权调用仍被后端拦。
import type { ShipmentStatus } from "@/lib/shipment";

/** 柜型 code(受控值域框架:应用层枚举,不落 DB CHECK;消费者仅表单校验)。 */
export const CONTAINER_TYPE_OPTIONS = [
  { value: "20GP", label: "20GP" },
  { value: "40GP", label: "40GP" },
  { value: "40HQ", label: "40HQ" },
  { value: "45HQ", label: "45HQ" },
] as const;

/**
 * 四态单线:组柜中(OPEN)→ 已封柜(LOADED)→ 已发运(DEPARTED)(+已取消 CANCELLED 终态)。
 * 色遵 DESIGN.md §1.3(只写语义名,不写色值,由 AntD 令牌下发):
 * 组柜中=processing(蓝/进行中)/ 已封柜=warning(橙金/待离港)/ 已发运=success(青/完成)/ 已取消=default(中性)。
 */
export const SHIPMENT_STATUS_META: Record<ShipmentStatus, { label: string; color: string }> = {
  OPEN: { label: "组柜中", color: "processing" },
  LOADED: { label: "已封柜", color: "warning" },
  DEPARTED: { label: "已发运", color: "success" },
  CANCELLED: { label: "已取消", color: "default" },
};

// 镜像转移矩阵(model SHIPMENT_ORDER_TRANSITIONS):
// OPEN→{LOADED,CANCELLED} / LOADED→{DEPARTED,OPEN}(撤封柜) / DEPARTED→{LOADED}(撤离港) / CANCELLED→{}。
const SHIPMENT_ORDER_TRANSITIONS: Record<ShipmentStatus, ShipmentStatus[]> = {
  OPEN: ["LOADED", "CANCELLED"],
  LOADED: ["DEPARTED", "OPEN"],
  DEPARTED: ["LOADED"],
  CANCELLED: [],
};

// 字段组(仅本模块内叙述,不落第二份;镜像 model 的 _CONTAINER_FIELDS / _SHIPPING_FIELDS)。
const CONTAINER_FIELDS = ["container_no", "container_type", "seal_no"] as const;
const SHIPPING_FIELDS = [
  "booking_no",
  "vessel_name",
  "voyage_no",
  "bl_no",
  "etd",
  "eta",
  "port_of_loading",
  "port_of_discharge",
] as const;

export type ShipmentField = (typeof CONTAINER_FIELDS)[number] | (typeof SHIPPING_FIELDS)[number] | "note";

/**
 * 镜像 model SHIPMENT_EDITABLE_FIELDS_BY_STATUS(每状态可改字段集,权威在后端 diff 式门禁):
 * OPEN=柜物理组+船务组+note / LOADED=船务组+note(封柜后柜物理组锁死) /
 * DEPARTED={bl_no,eta,note} / CANCELLED=空。
 */
export const SHIPMENT_EDITABLE_FIELDS_BY_STATUS: Record<ShipmentStatus, ReadonlySet<ShipmentField>> = {
  OPEN: new Set<ShipmentField>([...CONTAINER_FIELDS, ...SHIPPING_FIELDS, "note"]),
  LOADED: new Set<ShipmentField>([...SHIPPING_FIELDS, "note"]),
  DEPARTED: new Set<ShipmentField>(["bl_no", "eta", "note"]),
  CANCELLED: new Set<ShipmentField>(),
};

/** 某字段在当前状态是否可改(镜像后端门禁;前端据此禁用/隐藏输入)。 */
export const isFieldEditable = (s: ShipmentStatus, field: ShipmentField): boolean =>
  SHIPMENT_EDITABLE_FIELDS_BY_STATUS[s].has(field);

/** 当前状态是否有任何可编辑字段(有 → 显示编辑按钮)。 */
export const shipmentEditable = (s: ShipmentStatus): boolean =>
  SHIPMENT_EDITABLE_FIELDS_BY_STATUS[s].size > 0;

// 每个动作对应一条具名有向边(源→目标)。转移矩阵里同一目标态可从多源可达
// (如 LOADED 既是 OPEN 封柜的目标、也是 DEPARTED 撤离港的目标),故按「源态 + 该边合法」双判,
// 不能只查「目标 ∈ transitions」——否则会把撤离港误当封柜、把封柜误当撤离港。
const canTransit = (from: ShipmentStatus, to: ShipmentStatus): boolean =>
  SHIPMENT_ORDER_TRANSITIONS[from].includes(to);

/** 封柜确认 = OPEN→LOADED(后端守卫:非空柜 42004、全 ISSUED 否则 42003)。 */
export const shipmentLoadable = (s: ShipmentStatus): boolean =>
  s === "OPEN" && canTransit(s, "LOADED");
/** 撤封柜 = LOADED→OPEN(纠错口,清 loaded_at)。 */
export const shipmentUnloadable = (s: ShipmentStatus): boolean =>
  s === "LOADED" && canTransit(s, "OPEN");
/** 离港确认 = LOADED→DEPARTED(录 atd)。 */
export const shipmentDepartable = (s: ShipmentStatus): boolean =>
  s === "LOADED" && canTransit(s, "DEPARTED");
/** 撤离港 = DEPARTED→LOADED(纠错口,清 atd)。 */
export const shipmentUndepartable = (s: ShipmentStatus): boolean =>
  s === "DEPARTED" && canTransit(s, "LOADED");
/** 取消柜 = OPEN→CANCELLED(后端守卫:柜下无活动出库单,否则 42001)。 */
export const shipmentCancellable = (s: ShipmentStatus): boolean =>
  s === "OPEN" && canTransit(s, "CANCELLED");
