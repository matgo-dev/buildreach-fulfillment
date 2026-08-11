"use client";
import { useState, type ReactNode } from "react";
import {
  App,
  Button,
  Card,
  DatePicker,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Timeline,
} from "antd";
import { EditOutlined, PlusOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { useAuthStore } from "@/stores/authStore";
import { Permissions } from "@/config/permission-matrix";
import { colors } from "@/lib/tokens";
import { resolveBizError } from "@/lib/errorMessages";
import {
  shipmentApi,
  type LogisticsEventType,
  type LogisticsMilestone,
  type ShipmentEventOut,
} from "@/lib/shipment";
import {
  LOGISTICS_EVENT_TYPE_OPTIONS,
  LOGISTICS_MILESTONE_META,
} from "@/lib/logisticsMilestone";

// 物流轨迹卡:发运柜离港后在途里程碑(手动录入)。固定骨架 已离港 → 中转 → 到港。
// 已离港节点读柜 atd(派生,不入事件表);中转可多条;到港每柜至多一条(后端偏唯一 42009)。
// 仅 DEPARTED 柜有意义 —— 调用方据 shipment.status 决定是否挂本卡。

interface EditState {
  id: number | null; // null = 新建
  event_type: LogisticsEventType;
  event_at: dayjs.Dayjs | null;
  location: string;
  note: string;
}

const EMPTY_EDIT: EditState = {
  id: null,
  event_type: "TRANSSHIPMENT",
  event_at: null,
  location: "",
  note: "",
};

export function LogisticsTrackCard({
  shipmentId,
  atd,
  blNo,
  containerNo,
  events,
  currentStatus,
  onChanged,
}: {
  shipmentId: number;
  atd: string | null;
  // 追踪抬头:海运这票货的追踪身份 = 提单号(B/L)+ 柜号,单一源头在柜头,此处只回显。
  blNo: string | null;
  containerNo: string | null;
  events: ShipmentEventOut[];
  currentStatus: LogisticsMilestone | null;
  onChanged: () => void;
}) {
  const { message } = App.useApp();
  const [modalOpen, setModalOpen] = useState(false);
  const [edit, setEdit] = useState<EditState>(EMPTY_EDIT);
  const [busy, setBusy] = useState(false);

  const canManage = useAuthStore((s) => s.hasPermission(Permissions.SHIPMENT_MANAGE));
  const transships = events.filter((e) => e.event_type === "TRANSSHIPMENT");
  const arrived = events.find((e) => e.event_type === "ARRIVED") ?? null;

  // 日期边界镜像后端守卫:≥ATD;到港=终点 —— 非到港事件不晚于到港日、到港不早于已录事件最大日。
  const disabledDate = (d: dayjs.Dayjs) => {
    if (atd && d.isBefore(dayjs(atd), "day")) return true;
    if (edit.event_type === "ARRIVED") {
      const maxOther = events
        .filter((e) => e.id !== edit.id && e.event_type !== "ARRIVED")
        .reduce<string | null>((m, e) => (m === null || e.event_at > m ? e.event_at : m), null);
      return maxOther !== null && d.isBefore(dayjs(maxOther), "day");
    }
    return arrived !== null && arrived.id !== edit.id && d.isAfter(dayjs(arrived.event_at), "day");
  };

  function openCreate() {
    setEdit({ ...EMPTY_EDIT, event_at: atd ? dayjs(atd) : dayjs() });
    setModalOpen(true);
  }
  function openEdit(ev: ShipmentEventOut) {
    setEdit({
      id: ev.id,
      event_type: ev.event_type,
      event_at: dayjs(ev.event_at),
      location: ev.location ?? "",
      note: ev.note ?? "",
    });
    setModalOpen(true);
  }

  async function onSubmit() {
    if (!edit.event_at) {
      message.error("请填写事件日期");
      return;
    }
    const body = {
      event_type: edit.event_type,
      event_at: edit.event_at.format("YYYY-MM-DD"),
      location: edit.location.trim() || null,
      note: edit.note.trim() || null,
    };
    setBusy(true);
    try {
      if (edit.id === null) await shipmentApi.createEvent(shipmentId, body);
      else await shipmentApi.updateEvent(shipmentId, edit.id, body);
      message.success(edit.id === null ? "已录入里程碑" : "已更新");
      setModalOpen(false);
      onChanged();
    } catch (e) {
      // 42008 非 DEPARTED / 42009 到港唯一 / 40006 日期早于离港(errorMessages 映射中文)。
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(eventId: number) {
    setBusy(true);
    try {
      await shipmentApi.deleteEvent(shipmentId, eventId);
      message.success("已删除");
      onChanged();
    } catch (e) {
      message.error(resolveBizError(e, "删除失败"));
    } finally {
      setBusy(false);
    }
  }

  const rowActions = (ev: ShipmentEventOut) => (
    <Can perm={Permissions.SHIPMENT_MANAGE}>
      <Space size={4} style={{ marginLeft: 8 }}>
        <Button type="text" size="small" icon={<EditOutlined />} onClick={() => openEdit(ev)} />
        <Popconfirm
          title="删除该物流事件?"
          description="软删除,行保留供追溯。到港删除后可重录。"
          okButtonProps={{ danger: true }}
          onConfirm={() => onDelete(ev.id)}
        >
          <Button type="text" size="small" danger disabled={busy}>
            删除
          </Button>
        </Popconfirm>
      </Space>
    </Can>
  );

  const node = (title: string, when: string | null, extra?: ReactNode) => (
    <div>
      <div style={{ fontWeight: 600 }}>
        {title}
        {extra}
      </div>
      <div style={{ fontSize: 12, color: colors.muted }}>{when ?? "待到达"}</div>
    </div>
  );

  const eventBody = (ev: ShipmentEventOut, title: string) =>
    node(
      title,
      ev.event_at,
      <>
        {ev.location ? <span style={{ fontWeight: 400, marginLeft: 8 }}>{ev.location}</span> : null}
        {rowActions(ev)}
        {ev.note ? (
          <div style={{ fontWeight: 400, fontSize: 12, color: colors.muted, marginTop: 2 }}>
            {ev.note}
          </div>
        ) : null}
      </>,
    );

  // 骨架:已离港(atd)→ 中转(0..N)→ 到港(到了才显实节点)。录入入口不在卡右上,而在时间线
  // **末尾**(最后节点下):未到港时显 dashed「＋录入里程碑」引导继续录下一站;到港=范围终点
  // (提柜/清关不跟),收起录入入口。仅 shipment:manage 显示。
  const items = [
    { color: "blue", children: node("已离港", atd) },
    ...transships.map((ev) => ({ color: "blue", children: eventBody(ev, "中转") })),
    ...(arrived ? [{ color: "green", children: eventBody(arrived, "到港") }] : []),
    ...(!arrived && canManage
      ? [{
          dot: <PlusOutlined style={{ color: colors.brand }} />,
          children: (
            <Button type="link" style={{ padding: 0, height: "auto" }} onClick={openCreate}>
              录入里程碑
            </Button>
          ),
        }]
      : []),
  ];

  return (
    <Card
      title={
        <Space size={8}>
          <span>物流轨迹</span>
          {currentStatus ? (
            <StatusTag meta={LOGISTICS_MILESTONE_META} value={currentStatus} />
          ) : null}
        </Space>
      }
    >
      {/* 追踪抬头:提单号 / 柜号(货物追踪身份,凭此在船公司网站查轨迹)。 */}
      <div
        style={{
          display: "flex",
          gap: 24,
          marginBottom: 16,
          paddingBottom: 12,
          borderBottom: `1px solid ${colors.line}`,
          fontSize: 13,
        }}
      >
        <span style={{ color: colors.muted }}>
          提单号(B/L):<span style={{ color: colors.ink, fontWeight: 600 }}>{blNo || "—"}</span>
        </span>
        <span style={{ color: colors.muted }}>
          柜号:<span style={{ color: colors.ink, fontWeight: 600 }}>{containerNo || "—"}</span>
        </span>
      </div>
      <Timeline style={{ paddingTop: 8 }} items={items} />

      <Drawer
        title={edit.id === null ? "录入物流里程碑" : "编辑物流事件"}
        open={modalOpen}
        size="min(480px, 92vw)"
        destroyOnHidden
        onClose={() => setModalOpen(false)}
        footer={
          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button onClick={() => setModalOpen(false)} disabled={busy}>
              取消
            </Button>
            <Button type="primary" loading={busy} onClick={onSubmit}>
              保存
            </Button>
          </Space>
        }
      >
        <Form layout="vertical">
          <Form.Item label="里程碑" required>
            <Select
              value={edit.event_type}
              options={LOGISTICS_EVENT_TYPE_OPTIONS}
              onChange={(v) => setEdit((s) => ({ ...s, event_type: v }))}
            />
          </Form.Item>
          <Form.Item label="事件日期" required help="不早于实际离港日(ATD);到港为终点,在途事件不晚于到港日">
            <DatePicker
              style={{ width: "100%" }}
              allowClear={false}
              value={edit.event_at}
              disabledDate={disabledDate}
              onChange={(d) => setEdit((s) => ({ ...s, event_at: d }))}
            />
          </Form.Item>
          <Form.Item label="地点">
            <Input
              placeholder="选填,如 Singapore"
              maxLength={60}
              value={edit.location}
              onChange={(e) => setEdit((s) => ({ ...s, location: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="备注">
            <Input.TextArea
              rows={2}
              placeholder="选填"
              value={edit.note}
              onChange={(e) => setEdit((s) => ({ ...s, note: e.target.value }))}
            />
          </Form.Item>
        </Form>
      </Drawer>
    </Card>
  );
}
