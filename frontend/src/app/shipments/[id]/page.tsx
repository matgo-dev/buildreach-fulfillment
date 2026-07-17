"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { PageLoading } from "@/components/common/PageLoading";
import { Permissions } from "@/config/permission-matrix";
import { formatDateTime, formatQty } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  shipmentApi,
  type ShipmentDetail,
  type ShipmentOutboundSummary,
} from "@/lib/shipment";
import {
  SHIPMENT_STATUS_META,
  CONTAINER_TYPE_OPTIONS,
  shipmentEditable,
  shipmentCancellable,
} from "@/lib/shipmentStatus";
import { OUTBOUND_ORDER_STATUS_META } from "@/lib/outboundOrderStatus";
import { OutboundSalesOrderPicker } from "@/components/outbound/OutboundSalesOrderPicker";
import { OutboundOrderBuilder } from "@/components/outbound/OutboundOrderBuilder";

export default function ShipmentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const id = Number(params.id);

  const [detail, setDetail] = useState<ShipmentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  // 添加出库单流:先选 SO(picker),选定后带 SO id 打开建单器。
  const [pickerOpen, setPickerOpen] = useState(false);
  const [builderSoId, setBuilderSoId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDetail(await shipmentApi.get(id));
    } catch (e) {
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

  async function onSaveInfo() {
    const v = await form.validateFields().catch(() => null);
    if (!v) return;
    setBusy(true);
    try {
      await shipmentApi.update(id, {
        container_no: v.container_no?.trim() || null,
        container_type: v.container_type || null,
        seal_no: v.seal_no?.trim() || null,
        note: v.note?.trim() || null,
      });
      message.success("已保存柜信息");
      setEditOpen(false);
      load();
    } catch (e) {
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setBusy(false);
    }
  }

  async function onCancel() {
    setBusy(true);
    try {
      await shipmentApi.cancel(id);
      message.success("已取消发运柜");
      load();
    } catch (e) {
      // 42001:柜下有活动出库单不可取消(errorMessages 已映射中文)。
      message.error(resolveBizError(e, "取消失败"));
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
    {
      title: "客户",
      dataIndex: "customer_display",
      width: 170,
      ellipsis: true,
      render: (v: string | undefined) => v || "—",
    },
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

  if (loading || !detail) return <PageLoading />;

  const { shipment, outbound_orders } = detail;
  const canEdit = shipmentEditable(shipment.status);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
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
          <Space>
            <Can perm={Permissions.SHIPMENT_MANAGE}>
              {canEdit && (
                <Button
                  icon={<EditOutlined />}
                  onClick={() => {
                    form.setFieldsValue({
                      container_no: shipment.container_no ?? undefined,
                      container_type: shipment.container_type ?? undefined,
                      seal_no: shipment.seal_no ?? undefined,
                      note: shipment.note ?? undefined,
                    });
                    setEditOpen(true);
                  }}
                >
                  编辑柜信息
                </Button>
              )}
              {shipmentCancellable(shipment.status) && (
                <Popconfirm
                  title="取消该发运柜?"
                  description="取消后进入终态。柜下若存在活动出库单则不可取消。"
                  okButtonProps={{ danger: true }}
                  onConfirm={onCancel}
                >
                  <Button danger loading={busy}>
                    取消柜
                  </Button>
                </Popconfirm>
              )}
            </Can>
          </Space>
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

      <Card
        title="柜内出库单"
        extra={
          <Can perm={Permissions.OUTBOUND_MANAGE}>
            {canEdit && (
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => setPickerOpen(true)}
              >
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
                  {canEdit && (
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

      {/* 编辑柜信息:仅组柜中可改。 */}
      <Modal
        title="编辑柜信息"
        open={editOpen}
        okText="保存"
        confirmLoading={busy}
        onCancel={() => setEditOpen(false)}
        onOk={onSaveInfo}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item name="container_no" label="柜号">
            <Input placeholder="选填" />
          </Form.Item>
          <Form.Item name="container_type" label="柜型">
            <Select allowClear placeholder="选填" options={[...CONTAINER_TYPE_OPTIONS]} />
          </Form.Item>
          <Form.Item name="seal_no" label="封条号">
            <Input placeholder="选填" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input.TextArea rows={2} placeholder="选填" />
          </Form.Item>
        </Form>
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
