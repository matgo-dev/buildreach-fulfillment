"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { App, Button, Card, Descriptions, Popconfirm, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { PageLoading } from "@/components/common/PageLoading";
import { ListErrorState } from "@/components/common/ListErrorState";
import { OperationBlockedNotice } from "@/components/common/OperationBlockedNotice";
import { Permissions } from "@/config/permission-matrix";
import { ApiError } from "@/lib/api";
import { formatDateTime, formatQty } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  outboundOrderApi,
  type OutboundOrderDetail,
  type OutboundOrderLineOut,
} from "@/lib/outboundOrder";
import {
  OUTBOUND_ORDER_STATUS_META,
  outboundOrderEditable,
  outboundOrderConfirmable,
  outboundOrderCancellable,
} from "@/lib/outboundOrderStatus";
import { OutboundOrderBuilder } from "@/components/outbound/OutboundOrderBuilder";

/** 41902 可发不足明细行。后端 data 形状:{ items: [{ sku_id, name_snapshot, required_qty, available_qty }] }。 */
interface Shortage {
  label: string;
  required?: number | string;
  available?: number | string;
}

function parseShortages(data: unknown): Shortage[] {
  const arr = Array.isArray((data as { items?: unknown })?.items)
    ? (data as { items: unknown[] }).items
    : Array.isArray(data)
      ? data
      : [];
  return (arr as Record<string, unknown>[]).map((s) => ({
    label: String(s.name_snapshot ?? s.sku_id ?? "该 SKU"),
    required: s.required_qty as number | string | undefined,
    available: s.available_qty as number | string | undefined,
  }));
}

export default function OutboundOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message, modal } = App.useApp();
  const id = Number(params.id);

  const [detail, setDetail] = useState<OutboundOrderDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      setDetail(await outboundOrderApi.get(id));
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

  // 确认出库:41902 可发不足 → 按 sku 明细展示(其余走通用错误映射)。
  async function onConfirm() {
    setBusy(true);
    try {
      await outboundOrderApi.confirm(id);
      message.success("已确认出库");
      load();
    } catch (e) {
      if (e instanceof ApiError && e.code === 41902) {
        const rows = parseShortages(e.data);
        modal.error({
          title: "可发数量不足,无法出库",
          content: (
            <OperationBlockedNotice
              framed={false}
              title="可发数量不足,无法出库"
              nextAction="请减少本次出库数量,或先补足/释放可发库存后重试。"
              fallbackText="部分行可发库存不足,请减少数量或撤回后重试。"
              items={rows.map((s, i) => ({
                key: `${s.label}-${i}`,
                label: "库存明细",
                title: s.label,
                detail: [
                  s.required !== undefined ? `本次需 ${formatQty(s.required)}` : null,
                  s.available !== undefined ? `可发 ${formatQty(s.available)}` : null,
                ]
                  .filter(Boolean)
                  .join(" · "),
              }))}
            />
          ),
        });
      } else {
        message.error(resolveBizError(e, "操作失败"));
      }
    } finally {
      setBusy(false);
    }
  }

  // 出库单据无任何售价/成本列(契约 §3):明细只展示身份快照 + 数量。
  const columns: ColumnsType<OutboundOrderLineOut> = useMemo(
    () => [
      { title: "#", render: (_, __, i) => i + 1, width: 44 },
      { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
      { title: "规格", dataIndex: "spec_text_snapshot", ellipsis: true, render: (v) => v || "—" },
      { title: "单位", dataIndex: "unit_snapshot", width: 70 },
      { title: "出库数量", dataIndex: "qty", width: 110, align: "right", render: formatQty },
    ],
    [],
  );

  if (loadError && !detail) return <ListErrorState onRetry={load} />;
  if (loading || !detail) return <PageLoading />;

  const { order, lines } = detail;

  return (
    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title={
          <Space size={8}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => router.push("/outbound")}
              aria-label="返回列表"
            />
            <span>{order.no}</span>
            <StatusTag meta={OUTBOUND_ORDER_STATUS_META} value={order.status} />
          </Space>
        }
        extra={
          <Can perm={Permissions.OUTBOUND_MANAGE}>
            <Space>
              {outboundOrderEditable(order.status) && (
                <Button onClick={() => setEditing(true)}>编辑</Button>
              )}
              {outboundOrderConfirmable(order.status) && (
                <Button type="primary" loading={busy} onClick={onConfirm}>
                  确认出库
                </Button>
              )}
              {outboundOrderCancellable(order.status) && (
                <Popconfirm
                  title="取消该出库单?"
                  description="取消后进入终态。草稿未扣库存,取消不影响可发数量。"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => act(() => outboundOrderApi.cancel(id), "已取消")}
                >
                  <Button danger loading={busy}>
                    取消
                  </Button>
                </Popconfirm>
              )}
            </Space>
          </Can>
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="来源销售单">
            <Can perm={Permissions.SALES_READ} fallback={<span>{order.sales_order_no}</span>}>
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => router.push(`/sales/orders/${order.sales_order_id}`)}
              >
                {order.sales_order_no}
              </Button>
            </Can>
          </Descriptions.Item>
          <Descriptions.Item label="发运柜">
            {order.shipment_no ? (
              <Can
                perm={Permissions.SHIPMENT_READ}
                fallback={<span>{order.container_no || order.shipment_no}</span>}
              >
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  onClick={() => router.push(`/shipments/${order.shipment_id}`)}
                >
                  {order.container_no || order.shipment_no}
                </Button>
              </Can>
            ) : (
              "—"
            )}
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <StatusTag meta={OUTBOUND_ORDER_STATUS_META} value={order.status} />
          </Descriptions.Item>
          <Descriptions.Item label="确认时间">
            {order.issued_at ? formatDateTime(order.issued_at) : "—"}
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            {order.note || "—"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="出库明细">
        <Table<OutboundOrderLineOut>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={lines}
          pagination={false}
          scroll={{ x: 640 }}
        />
      </Card>

      {/* 编辑(仅草稿):挑行 / 改数量,整单保存带乐观锁。 */}
      <OutboundOrderBuilder
        open={editing}
        mode="edit"
        salesOrderId={order.sales_order_id}
        orderId={id}
        onClose={() => setEditing(false)}
        onSaved={() => {
          setEditing(false);
          load();
        }}
      />

    </Space>
  );
}
