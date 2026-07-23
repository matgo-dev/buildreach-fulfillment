"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
  DatePicker,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Timeline,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { PageLoading } from "@/components/common/PageLoading";
import { ListErrorState } from "@/components/common/ListErrorState";
import { Permissions } from "@/config/permission-matrix";
import { ApiError } from "@/lib/api";
import { formatDateTime, formatQty } from "@/lib/format";
import { colors } from "@/lib/tokens";
import { resolveBizError } from "@/lib/errorMessages";
import {
  shipmentApi,
  type ShipmentDetail,
  type ShipmentOut,
  type ShipmentOutboundSummary,
  type ShipmentUpdateBody,
} from "@/lib/shipment";
import {
  SHIPMENT_STATUS_META,
  CONTAINER_TYPE_OPTIONS,
  isFieldEditable,
  shipmentEditable,
  shipmentLoadable,
  shipmentUnloadable,
  shipmentDepartable,
  shipmentUndepartable,
  shipmentCancellable,
  type ShipmentField,
} from "@/lib/shipmentStatus";
import { OUTBOUND_ORDER_STATUS_META } from "@/lib/outboundOrderStatus";
import { OutboundSalesOrderPicker } from "@/components/outbound/OutboundSalesOrderPicker";
import { OutboundOrderBuilder } from "@/components/outbound/OutboundOrderBuilder";
import { LogisticsTrackCard } from "@/components/shipment/LogisticsTrackCard";
import { CustomsCard } from "@/components/shipment/CustomsCard";

// 编辑按钮文案随状态变(可编辑字段集不同,直接点出能改啥):OPEN 全量柜信息 /
// LOADED 船务信息 / DEPARTED 仅提单号·ETA·备注可补(提单常离港后签发,故点名提单/ETA)。
const EDIT_LABEL: Record<string, string> = {
  OPEN: "编辑柜信息",
  LOADED: "编辑船务信息",
  DEPARTED: "补录提单/ETA",
};

export default function ShipmentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message, modal } = App.useApp();
  const [form] = Form.useForm();
  const [loadForm] = Form.useForm();
  const [departForm] = Form.useForm();
  const id = Number(params.id);

  const [detail, setDetail] = useState<ShipmentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [loadOpen, setLoadOpen] = useState(false);
  const [departOpen, setDepartOpen] = useState(false);
  // 添加出库单流:先选 SO(picker),选定后带 SO id 打开建单器。
  const [pickerOpen, setPickerOpen] = useState(false);
  const [builderSoId, setBuilderSoId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      setDetail(await shipmentApi.get(id));
    } catch (e) {
      setLoadError(true);
      message.error(resolveBizError(e, "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [id, message]);

  useEffect(() => {
    load();
  }, [load]);

  // 本柜已有活动出库单(非已取消)的来源 SO —— 传给 picker 做前端预拦。
  const activeSoIds = useMemo(
    () =>
      (detail?.outbound_orders ?? [])
        .filter((o) => o.status !== "CANCELLED")
        .map((o) => o.sales_order_id),
    [detail],
  );

  // 打开编辑:按当前状态可编辑字段集回填表单(日期字段转 dayjs)。
  function openEdit(s: ShipmentOut) {
    form.setFieldsValue({
      container_no: s.container_no ?? undefined,
      container_type: s.container_type ?? undefined,
      seal_no: s.seal_no ?? undefined,
      booking_no: s.booking_no ?? undefined,
      vessel_name: s.vessel_name ?? undefined,
      voyage_no: s.voyage_no ?? undefined,
      bl_no: s.bl_no ?? undefined,
      port_of_loading: s.port_of_loading ?? undefined,
      port_of_discharge: s.port_of_discharge ?? undefined,
      etd: s.etd ? dayjs(s.etd) : undefined,
      eta: s.eta ? dayjs(s.eta) : undefined,
      note: s.note ?? undefined,
    });
    setEditOpen(true);
  }

  async function onSaveInfo() {
    if (!detail) return;
    const s = detail.shipment;
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    // 稀疏 PATCH:只提交当前状态可编辑字段(其余后端不动),携乐观锁基线。表单本就只渲染
    // 可编辑字段,故直接按 isFieldEditable 收集即可,无需回填不可改字段。
    const ed = (f: ShipmentField) => isFieldEditable(s.status, f);
    const patch: Record<string, string | null> = {};
    const TXT: ShipmentField[] = [
      "container_no", "seal_no", "booking_no", "vessel_name", "voyage_no",
      "bl_no", "port_of_loading", "port_of_discharge", "note",
    ];
    for (const f of TXT) {
      if (ed(f)) patch[f] = (v[f] as string | undefined)?.trim() || null;
    }
    if (ed("container_type")) patch.container_type = (v.container_type as string) || null;
    for (const f of ["etd", "eta"] as const) {
      if (ed(f)) patch[f] = v[f] ? (v[f] as dayjs.Dayjs).format("YYYY-MM-DD") : null;
    }
    const body: ShipmentUpdateBody = { ...patch, expected_updated_at: s.updated_at };
    setBusy(true);
    try {
      await shipmentApi.update(id, body);
      message.success("已保存柜信息");
      setEditOpen(false);
      load();
    } catch (e) {
      // 42005 当前状态不可修改该字段 / 42006 冲突(errorMessages 已映射中文)。
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setBusy(false);
    }
  }

  // 封柜确认:守卫 42003(草稿单号列表)/ 42004(空柜),按明细展示;
  // 补录覆盖柜号/封条 → 携乐观锁基线(冲突 42006 提示刷新)。
  async function onLoad() {
    if (!detail) return;
    const v = await loadForm.validateFields().catch(() => null);
    if (!v) return;
    setBusy(true);
    try {
      await shipmentApi.load(id, {
        container_no: v.container_no?.trim() || null,
        seal_no: v.seal_no?.trim() || null,
        expected_updated_at: detail.shipment.updated_at,
      });
      message.success("已封柜确认");
      setLoadOpen(false);
      loadForm.resetFields();
      load();
    } catch (e) {
      if (e instanceof ApiError && e.code === 42003) {
        const nos = (e.data as { draft_nos?: string[] } | null)?.draft_nos ?? [];
        modal.error({
          title: "柜内存在草稿出库单,不可封柜",
          content: (
            <div style={{ marginTop: 8 }}>
              <div style={{ marginBottom: 6 }}>请先确认或移除以下草稿出库单后再封柜:</div>
              {nos.map((no) => (
                <div key={no} style={{ fontSize: 13 }}>
                  {no}
                </div>
              ))}
            </div>
          ),
        });
      } else {
        message.error(resolveBizError(e, "封柜失败"));
      }
    } finally {
      setBusy(false);
    }
  }

  // 离港确认:atd 必填(后端 422 兜底),表单预填本地今日、可改——「默认今天」只活在这里,
  // 服务端不以 UTC 猜业务日期。
  async function onDepart() {
    const v = await departForm.validateFields().catch(() => null);
    if (!v) return;
    setBusy(true);
    try {
      await shipmentApi.depart(id, { atd: (v.atd as dayjs.Dayjs).format("YYYY-MM-DD") });
      message.success("已离港确认");
      setDepartOpen(false);
      load();
    } catch (e) {
      message.error(resolveBizError(e, "离港确认失败"));
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      message.success(ok);
      load();
    } catch (e) {
      message.error(resolveBizError(e, "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnsType<ShipmentOutboundSummary> = [
    { title: "出库单号", dataIndex: "no", width: 150 },
    {
      title: "销售单号",
      dataIndex: "sales_order_no",
      width: 150,
      render: (v: string, r) => (
        <Can perm={Permissions.SALES_READ} fallback={<span>{v}</span>}>
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/sales/orders/${r.sales_order_id}`);
            }}
          >
            {v}
          </Button>
        </Can>
      ),
    },
    { title: "客户", dataIndex: "customer_display", width: 170, ellipsis: true },
    {
      title: "行数 / 件数",
      key: "qty",
      width: 120,
      align: "right",
      render: (_, r) => `${r.line_count} / ${formatQty(r.total_qty)}`,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: ShipmentOutboundSummary["status"]) => (
        <StatusTag meta={OUTBOUND_ORDER_STATUS_META} value={s} />
      ),
    },
  ];

  if (loadError && !detail) return <ListErrorState onRetry={load} />;
  if (loading || !detail) return <PageLoading />;

  const { shipment, outbound_orders } = detail;
  const canEdit = shipmentEditable(shipment.status);
  // 柜内可加/管出库单仅组柜中(封柜后柜内出库单冻结,镜像后端 41906/41910)。
  const isOpen = shipment.status === "OPEN";

  // 时间线三节点:建柜(必达)→ 封柜(loaded_at)→ 离港(atd),已发生亮蓝、未发生灰。
  const timelineItems = [
    {
      color: "blue",
      children: (
        <div>
          <div style={{ fontWeight: 600 }}>建柜</div>
          <div style={{ fontSize: 12, color: colors.muted }}>{formatDateTime(shipment.created_at)}</div>
        </div>
      ),
    },
    {
      color: shipment.loaded_at ? "blue" : "gray",
      children: (
        <div>
          <div style={{ fontWeight: 600 }}>封柜</div>
          <div style={{ fontSize: 12, color: colors.muted }}>
            {shipment.loaded_at ? formatDateTime(shipment.loaded_at) : "待封柜"}
          </div>
        </div>
      ),
    },
    {
      color: shipment.atd ? "blue" : "gray",
      children: (
        <div>
          <div style={{ fontWeight: 600 }}>离港</div>
          <div style={{ fontSize: 12, color: colors.muted }}>{shipment.atd || "待离港"}</div>
        </div>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {/* 顶部柜卡:柜物理信息 + 状态徽标 + 动作按钮区(按 status × SHIPMENT_MANAGE 渲染)。 */}
      <Card
        title={
          <Space size={8}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => router.push("/shipments")}
              aria-label="返回列表"
            />
            <span>{shipment.no}</span>
            <StatusTag meta={SHIPMENT_STATUS_META} value={shipment.status} />
          </Space>
        }
        extra={
          <Can perm={Permissions.SHIPMENT_MANAGE}>
            <Space>
              {canEdit && (
                <Button icon={<EditOutlined />} onClick={() => openEdit(shipment)}>
                  {EDIT_LABEL[shipment.status] ?? "编辑"}
                </Button>
              )}
              {shipmentLoadable(shipment.status) && (
                <Button
                  type="primary"
                  onClick={() => {
                    loadForm.setFieldsValue({
                      container_no: shipment.container_no ?? undefined,
                      seal_no: shipment.seal_no ?? undefined,
                    });
                    setLoadOpen(true);
                  }}
                >
                  封柜确认
                </Button>
              )}
              {shipmentDepartable(shipment.status) && (
                <Button
                  type="primary"
                  onClick={() => {
                    departForm.setFieldsValue({ atd: shipment.atd ? dayjs(shipment.atd) : dayjs() });
                    setDepartOpen(true);
                  }}
                >
                  离港确认
                </Button>
              )}
              {shipmentUnloadable(shipment.status) && (
                <Popconfirm
                  title="撤封柜?"
                  description="撤回到组柜中,清空封柜时间,柜内出库单解冻可再编辑。用于纠错未离港的误封柜。"
                  onConfirm={() => act(() => shipmentApi.unload(id), "已撤封柜")}
                >
                  <Button loading={busy}>撤封柜</Button>
                </Popconfirm>
              )}
              {shipmentUndepartable(shipment.status) && (
                <Popconfirm
                  title="撤离港?"
                  description="撤回到已封柜,清空实际离港日(ATD)。用于纠正误点的离港确认。"
                  onConfirm={() => act(() => shipmentApi.undepart(id), "已撤离港")}
                >
                  <Button loading={busy}>撤离港</Button>
                </Popconfirm>
              )}
              {shipmentCancellable(shipment.status) && (
                <Popconfirm
                  title="取消该发运柜?"
                  description="取消后进入终态。柜下若存在活动出库单则不可取消。"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => act(() => shipmentApi.cancel(id), "已取消发运柜")}
                >
                  <Button danger loading={busy}>
                    取消柜
                  </Button>
                </Popconfirm>
              )}
            </Space>
          </Can>
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="柜号">{shipment.container_no || "—"}</Descriptions.Item>
          <Descriptions.Item label="柜型">{shipment.container_type || "—"}</Descriptions.Item>
          <Descriptions.Item label="封条号">{shipment.seal_no || "—"}</Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {formatDateTime(shipment.created_at)}
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            {shipment.note || "—"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 船务信息卡 + 时间线并排。 */}
      <div
        style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 220px", gap: 16 }}
      >
        <Card title="船务信息">
          <Descriptions column={2} size="small" bordered>
            <Descriptions.Item label="订舱号">{shipment.booking_no || "—"}</Descriptions.Item>
            <Descriptions.Item label="船名">{shipment.vessel_name || "—"}</Descriptions.Item>
            <Descriptions.Item label="航次">{shipment.voyage_no || "—"}</Descriptions.Item>
            <Descriptions.Item label="提单号">{shipment.bl_no || "—"}</Descriptions.Item>
            <Descriptions.Item label="起运港">{shipment.port_of_loading || "—"}</Descriptions.Item>
            <Descriptions.Item label="目的港">
              {shipment.port_of_discharge || "—"}
            </Descriptions.Item>
            <Descriptions.Item label="ETD(预计离港)">{shipment.etd || "—"}</Descriptions.Item>
            <Descriptions.Item label="ETA(预计到港)">{shipment.eta || "—"}</Descriptions.Item>
            <Descriptions.Item label="ATD(实际离港)">{shipment.atd || "—"}</Descriptions.Item>
            <Descriptions.Item label="封柜时间">
              {shipment.loaded_at ? formatDateTime(shipment.loaded_at) : "—"}
            </Descriptions.Item>
          </Descriptions>
        </Card>
        <Card title="发运进度">
          <Timeline style={{ paddingTop: 8 }} items={timelineItems} />
        </Card>
      </div>

      {/* 报关:封柜/离港后子资源。业务时序=封柜→报关→离港→物流,故报关卡在物流轨迹卡之前。
          仅 customs_status!==null(LOADED/DEPARTED 柜)挂本卡;OPEN/CANCELLED 柜不适用。 */}
      {detail.customs_status !== null && (
        <CustomsCard
          shipmentId={id}
          shipmentStatus={shipment.status}
          customsStatus={detail.customs_status}
          declaration={detail.customs_declaration}
          onChanged={load}
        />
      )}

      {/* 物流轨迹:柜离港后在途里程碑(中转/到港手动录入)。仅已发运柜显 —— 未离港无在途轨迹。 */}
      {shipment.status === "DEPARTED" && (
        <LogisticsTrackCard
          shipmentId={id}
          atd={shipment.atd}
          blNo={shipment.bl_no}
          containerNo={shipment.container_no}
          events={detail.logistics_events}
          currentStatus={detail.current_logistics_status}
          onChanged={load}
        />
      )}

      <Card
        title="柜内出库单"
        extra={
          <Can perm={Permissions.OUTBOUND_MANAGE}>
            {isOpen && (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
                添加出库单
              </Button>
            )}
          </Can>
        }
      >
        <Table<ShipmentOutboundSummary>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={outbound_orders}
          pagination={false}
          scroll={{ x: 690 }}
          locale={{
            emptyText: (
              <Empty description="柜内暂无出库单">
                <Can perm={Permissions.OUTBOUND_MANAGE}>
                  {isOpen && (
                    <Button
                      type="primary"
                      icon={<PlusOutlined />}
                      onClick={() => setPickerOpen(true)}
                    >
                      添加出库单
                    </Button>
                  )}
                </Can>
              </Empty>
            ),
          }}
          onRow={(r) => ({
            onClick: () => router.push(`/outbound/${r.id}`),
            style: { cursor: "pointer" },
          })}
        />
      </Card>

      {/* 编辑:按当前状态可编辑字段集渲染(不可编辑字段不显);全量保存带乐观锁。 */}
      <Modal
        title={EDIT_LABEL[shipment.status] ?? "编辑柜信息"}
        open={editOpen}
        okText="保存"
        confirmLoading={busy}
        onCancel={() => setEditOpen(false)}
        onOk={onSaveInfo}
        width={560}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          {isFieldEditable(shipment.status, "container_no") && (
            <Form.Item name="container_no" label="柜号">
              <Input placeholder="选填" maxLength={20} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "container_type") && (
            <Form.Item name="container_type" label="柜型">
              <Select allowClear placeholder="选填" options={[...CONTAINER_TYPE_OPTIONS]} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "seal_no") && (
            <Form.Item name="seal_no" label="封条号">
              <Input placeholder="选填" maxLength={30} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "booking_no") && (
            <Form.Item name="booking_no" label="订舱号">
              <Input placeholder="选填" maxLength={30} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "vessel_name") && (
            <Form.Item name="vessel_name" label="船名">
              <Input placeholder="选填" maxLength={60} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "voyage_no") && (
            <Form.Item name="voyage_no" label="航次">
              <Input placeholder="选填" maxLength={20} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "bl_no") && (
            <Form.Item name="bl_no" label="提单号">
              <Input placeholder="选填,提单常在离港后签发" maxLength={40} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "port_of_loading") && (
            <Form.Item name="port_of_loading" label="起运港">
              <Input placeholder="选填" maxLength={60} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "port_of_discharge") && (
            <Form.Item name="port_of_discharge" label="目的港">
              <Input placeholder="选填" maxLength={60} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "etd") && (
            <Form.Item name="etd" label="ETD(预计离港)">
              <DatePicker style={{ width: "100%" }} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "eta") && (
            <Form.Item name="eta" label="ETA(预计到港)">
              <DatePicker style={{ width: "100%" }} />
            </Form.Item>
          )}
          {isFieldEditable(shipment.status, "note") && (
            <Form.Item name="note" label="备注">
              <Input.TextArea rows={2} placeholder="选填" />
            </Form.Item>
          )}
        </Form>
      </Modal>

      {/* 封柜确认:可补录封条/柜号(封号贴封条时才知道)。 */}
      <Modal
        title="封柜确认"
        open={loadOpen}
        okText="确认封柜"
        confirmLoading={busy}
        onCancel={() => {
          setLoadOpen(false);
          loadForm.resetFields();
        }}
        onOk={onLoad}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <span>
            封柜确认后柜进入「已封柜」,柜内出库单冻结(不可撤销/编辑)。要求柜内至少 1
            张出库单且全部已确认出库。可在此补录封条号 / 柜号。
          </span>
          <Form form={loadForm} layout="vertical">
            <Form.Item name="container_no" label="柜号(可补录)">
              <Input placeholder="选填" maxLength={20} />
            </Form.Item>
            <Form.Item name="seal_no" label="封条号(可补录)">
              <Input placeholder="选填" maxLength={30} />
            </Form.Item>
          </Form>
        </Space>
      </Modal>

      {/* 离港确认:atd 默认今日,可改。 */}
      <Modal
        title="离港确认"
        open={departOpen}
        okText="确认离港"
        confirmLoading={busy}
        onCancel={() => setDepartOpen(false)}
        onOk={onDepart}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <span>确认后柜进入「已发运」。请填写实际离港日(ATD)。</span>
          <Form form={departForm} layout="vertical">
            <Form.Item
              name="atd"
              label="实际离港日(ATD)"
              rules={[{ required: true, message: "请填写实际离港日" }]}
            >
              <DatePicker style={{ width: "100%" }} allowClear={false} />
            </Form.Item>
          </Form>
        </Space>
      </Modal>

      {/* 添加出库单流:选 SO → 建单器挑行录数量。 */}
      <OutboundSalesOrderPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        activeSoIds={activeSoIds}
        onPick={(soId) => {
          setPickerOpen(false);
          setBuilderSoId(soId);
        }}
      />
      <OutboundOrderBuilder
        open={builderSoId !== null}
        mode="create"
        shipmentId={id}
        salesOrderId={builderSoId ?? 0}
        onClose={() => setBuilderSoId(null)}
        onSaved={() => {
          setBuilderSoId(null);
          load();
        }}
      />
    </Space>
  );
}
