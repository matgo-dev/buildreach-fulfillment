// 发运柜前端类型 + API。对齐后端 schemas/shipment.py。
// 柜 = 组柜容器 + 船务生命周期(封柜/离港)。无红线字段(成本/供应商/售价)。
import { api } from "./api";
import type { Page } from "./catalog";
import type { OutboundOrderStatus } from "./outboundOrder";

export type ShipmentStatus = "OPEN" | "LOADED" | "DEPARTED" | "CANCELLED";

// 物流里程碑(镜像 backend LogisticsMilestone;已离港 DEPARTED 是派生态,不入事件表)。
export type LogisticsMilestone = "DEPARTED" | "TRANSSHIPMENT" | "ARRIVED";
// 可录入事件类型(EVENT_TYPES:中转/到港);已离港不可录。
export type LogisticsEventType = "TRANSSHIPMENT" | "ARRIVED";

export interface ShipmentOut {
  id: number;
  no: string;
  container_no: string | null;
  container_type: string | null;
  seal_no: string | null;
  note: string | null;
  // 船务字段(§D5,逐步补录)。
  booking_no: string | null;
  vessel_name: string | null;
  voyage_no: string | null;
  bl_no: string | null;
  port_of_loading: string | null;
  port_of_discharge: string | null;
  // 时间(date;§D4)。etd 计划 / eta 预计到港 / atd 实际离港(离港确认录)。
  etd: string | null;
  eta: string | null;
  atd: string | null;
  // 封柜确认系统时刻(datetime;时间线消费者)。
  loaded_at: string | null;
  status: ShipmentStatus;
  updated_at: string;
  created_at: string;
}

export interface ShipmentListItem {
  id: number;
  no: string;
  container_no: string | null;
  container_type: string | null;
  seal_no: string | null;
  vessel_name: string | null;
  voyage_no: string | null;
  etd: string | null;
  atd: string | null;
  status: ShipmentStatus;
  /** 柜内出库单数(含草稿,不含已取消)。 */
  outbound_count: number;
  /** 当前物流状态(纯派生):非 DEPARTED 柜为 null(显「—」);否则已离港/中转/到港。 */
  current_logistics_status: LogisticsMilestone | null;
  created_at: string;
}

/** 物流轨迹事件(离港后在途里程碑)。无红线字段。 */
export interface ShipmentEventOut {
  id: number;
  event_type: LogisticsEventType;
  event_at: string;
  location: string | null;
  note: string | null;
  created_at: string;
}

/** 柜内出库单摘要(组柜工作台表)。 */
export interface ShipmentOutboundSummary {
  id: number;
  no: string;
  sales_order_id: number;
  sales_order_no: string;
  customer_display: string;
  line_count: number;
  total_qty: number | string;
  status: OutboundOrderStatus;
}

export interface ShipmentDetail {
  shipment: ShipmentOut;
  outbound_orders: ShipmentOutboundSummary[];
  /** 物流轨迹活动事件(正序 event_at ASC);已离港节点读 shipment.atd,不在此列。 */
  logistics_events: ShipmentEventOut[];
  /** 当前物流状态(纯派生);非 DEPARTED 柜为 null。 */
  current_logistics_status: LogisticsMilestone | null;
}

/** 录入物流里程碑入参。event_at 为事件业务日(后端另校验 ≥ 柜 atd)。 */
export interface ShipmentEventCreateBody {
  event_type: LogisticsEventType;
  event_at: string;
  location?: string | null;
  note?: string | null;
}

/** 改物流事件入参(稀疏:仅传入字段覆盖)。 */
export interface ShipmentEventUpdateBody {
  event_type?: LogisticsEventType;
  event_at?: string;
  location?: string | null;
  note?: string | null;
}

/**
 * 建柜入参(POST)。船务字段建柜即录(可选);atd 由离港确认动作驱动,不走整单保存。
 */
export interface ShipmentSaveBody {
  container_no?: string | null;
  container_type?: string | null;
  seal_no?: string | null;
  note?: string | null;
  booking_no?: string | null;
  vessel_name?: string | null;
  voyage_no?: string | null;
  bl_no?: string | null;
  port_of_loading?: string | null;
  port_of_discharge?: string | null;
  etd?: string | null;
  eta?: string | null;
}

/**
 * 改柜入参(PATCH,稀疏):仅传入字段参与门禁 + 覆盖(未传字段不动)。
 * `expected_updated_at` **必填**(对齐出库/入库/PO 乐观锁,漏传后端 422);冲突 → 42006。
 */
export interface ShipmentUpdateBody extends ShipmentSaveBody {
  /** 乐观锁基线 = 打开编辑时的 shipment.updated_at。 */
  expected_updated_at: string;
}

/** 封柜确认入参:可补录封条/柜号(封号贴封条时才知道)。补录覆盖已有值,
 * 故与 PATCH 同口径携乐观锁基线(必填,漏传后端 422;冲突 42006)。 */
export interface ShipmentLoadBody {
  container_no?: string | null;
  seal_no?: string | null;
  /** 乐观锁基线 = 打开封柜弹窗时的 shipment.updated_at。 */
  expected_updated_at: string;
}

/** 离港确认入参:atd 实际离港日,必填(业务日期由操作者按本地时区给出,服务端不猜「当日」)。 */
export interface ShipmentDepartBody {
  atd: string;
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export interface ShipmentListFilters {
  status?: string;
  keyword?: string;
  /** 当前物流状态(派生)筛选:DEPARTED(已离港)/TRANSSHIPMENT(中转)/ARRIVED(到港)。 */
  logistics_status?: string;
  page?: number;
  size?: number;
}

export const shipmentApi = {
  list: (p: ShipmentListFilters) =>
    api.get<Page<ShipmentListItem>>(`/api/v1/shipments${qs(p as Record<string, unknown>)}`),
  get: (id: number) => api.get<ShipmentDetail>(`/api/v1/shipments/${id}`),
  create: (b: ShipmentSaveBody) => api.post<ShipmentDetail>("/api/v1/shipments", b),
  update: (id: number, b: ShipmentUpdateBody) =>
    api.patch<ShipmentDetail>(`/api/v1/shipments/${id}`, b),
  /** 封柜确认 OPEN→LOADED(守卫:非空柜且全 ISSUED,否则 42003/42004)。 */
  load: (id: number, b: ShipmentLoadBody) =>
    api.post<ShipmentDetail>(`/api/v1/shipments/${id}/load`, b),
  /** 撤封柜 LOADED→OPEN(清 loaded_at,解冻柜内出库单)。 */
  unload: (id: number) => api.post<ShipmentDetail>(`/api/v1/shipments/${id}/unload`),
  /** 离港确认 LOADED→DEPARTED(录 atd)。 */
  depart: (id: number, b: ShipmentDepartBody) =>
    api.post<ShipmentDetail>(`/api/v1/shipments/${id}/depart`, b),
  /** 撤离港 DEPARTED→LOADED(清 atd;守卫:柜下有活动物流事件则 42007)。 */
  undepart: (id: number) => api.post<ShipmentDetail>(`/api/v1/shipments/${id}/undepart`),
  cancel: (id: number) => api.post<ShipmentDetail>(`/api/v1/shipments/${id}/cancel`),
  // ---- 物流轨迹事件(发运柜子资源;录/改/删前置柜 DEPARTED)----
  /** 录入里程碑(中转/到港)。守卫:非 DEPARTED 42008 / 到港唯一 42009 / event_at<atd 400。 */
  createEvent: (id: number, b: ShipmentEventCreateBody) =>
    api.post<ShipmentDetail>(`/api/v1/shipments/${id}/logistics-events`, b),
  /** 改事件(纠错)。 */
  updateEvent: (id: number, eventId: number, b: ShipmentEventUpdateBody) =>
    api.patch<ShipmentDetail>(`/api/v1/shipments/${id}/logistics-events/${eventId}`, b),
  /** 软删事件。 */
  deleteEvent: (id: number, eventId: number) =>
    api.del<ShipmentDetail>(`/api/v1/shipments/${id}/logistics-events/${eventId}`),
};
