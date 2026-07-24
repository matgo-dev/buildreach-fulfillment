"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { App, Button, Card, Descriptions, Popconfirm, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ProgressCell } from "@/components/common/ProgressCell";
import { PageLoading } from "@/components/common/PageLoading";
import { ListErrorState } from "@/components/common/ListErrorState";
import { Permissions } from "@/config/permission-matrix";
import { useAuthStore } from "@/stores/authStore";
import { formatDateTime, formatQty } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  formatCost,
  purchaseOrderApi,
  type PurchaseOrderLineOut,
  type PurchaseOrderOut,
  type RelatedInboundOrder,
} from "@/lib/purchaseOrder";
import {
  PURCHASE_ORDER_STATUS_META,
  purchaseOrderCancellable,
  purchaseOrderConfirmable,
  purchaseOrderEditable,
} from "@/lib/purchaseOrderStatus";
import {
  INBOUND_ORDER_STATUS_META,
  RECEIPT_PROGRESS_META,
} from "@/lib/inboundOrderStatus";
import { InTransitBadge } from "@/components/inbound/InTransitBadge";
import { PurchaseOrderBuilder } from "@/components/purchasing/PurchaseOrderBuilder";

export default function PurchaseOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message } = App.useApp();
  const id = Number(params.id);
  // 🔴 成本红线可见性:无权者后端已脱敏,渲染层整列/整项藏掉(DESIGN.md §9)。
  const canSeeCost = useAuthStore((s) => s.hasPermission(Permissions.PURCHASE_READ_COST));

  const [order, setOrder] = useState<PurchaseOrderOut | null>(null);
  const [lines, setLines] = useState<PurchaseOrderLineOut[]>([]);
  const [inbounds, setInbounds] = useState<RelatedInboundOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const { order: o, lines: ls, inbound_orders: ibs } = await purchaseOrderApi.get(id);
      setOrder(o);
      setLines(ls);
      setInbounds(ibs);
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

  const columns: ColumnsType<PurchaseOrderLineOut> = useMemo(
    () => [
      { title: "#", render: (_, __, i) => i + 1, width: 44 },
      { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
      { title: "规格", dataIndex: "spec_text_snapshot", ellipsis: true, render: (v) => v || "—" },
      { title: "单位", dataIndex: "unit_snapshot", width: 70 },
      { title: "数量", dataIndex: "qty", width: 90, align: "right", render: formatQty },
      {
        title: "在途",
        dataIndex: "in_transit_qty",
        width: 80,
        align: "right",
        render: (v) => (v === undefined || v === null ? "—" : formatQty(v)),
      },
      {
        title: "已入",
        dataIndex: "received_qty",
        width: 80,
        align: "right",
        render: (v) => (v === undefined || v === null ? "—" : formatQty(v)),
      },
      {
        title: "剩余",
        key: "remaining",
        width: 80,
        align: "right",
        render: (_, r) => {
          if (r.received_qty === undefined || r.received_qty === null) return "—";
          const remaining = Number(r.qty) - Number(r.received_qty) - Number(r.in_transit_qty ?? 0);
          return formatQty(remaining);
        },
      },
      // 🔴 成本红线:无 purchase:read_cost 者整两列不渲染(DESIGN.md §9)。
      ...((canSeeCost
        ? [
            { title: "采购价", dataIndex: "unit_price", width: 120, align: "right", render: formatCost },
            { title: "行额", dataIndex: "line_total", width: 130, align: "right", render: formatCost },
          ]
        : []) as ColumnsType<PurchaseOrderLineOut>),
      { title: "备注", dataIndex: "remark", ellipsis: true, render: (v) => v || "—" },
    ],
    [canSeeCost],
  );

  if (loadError && !order) return <ListErrorState onRetry={load} />;
  if (loading || !order) return <PageLoading />;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title={
          <Space size={8}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => router.push("/purchasing/orders")}
              aria-label="返回列表"
            />
            <span>{order.no}</span>
            <StatusTag meta={PURCHASE_ORDER_STATUS_META} value={order.status} />
            {order.receipt_progress && (
              <ProgressCell meta={RECEIPT_PROGRESS_META} value={order.receipt_progress} />
            )}
            {/* 在途信号从已加载的入库记录派生(IN_TRANSIT 计数),与收货进度并列弱化。 */}
            <InTransitBadge count={inbounds.filter((i) => i.status === "IN_TRANSIT").length} />
          </Space>
        }
        extra={
          <Can perm={Permissions.PURCHASE_MANAGE}>
            <Space>
              {purchaseOrderEditable(order.status) && (
                <Button onClick={() => setEditing(true)}>编辑</Button>
              )}
              {purchaseOrderConfirmable(order.status) && (
                <Popconfirm
                  title="确认该采购单?"
                  description="确认后进入已确认态,不可再编辑。"
                  okText="确认"
                  onConfirm={() => act(() => purchaseOrderApi.confirm(id), "已确认")}
                >
                  <Button type="primary" loading={busy}>
                    确认
                  </Button>
                </Popconfirm>
              )}
              {purchaseOrderCancellable(order.status) && (
                <Popconfirm
                  title="取消该采购单?"
                  description="取消后进入终态,释放对销售单的采购占用。"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => act(() => purchaseOrderApi.cancel(id), "已取消")}
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
          <Descriptions.Item label="供应商">
            {order.supplier_display ?? `#${order.supplier_id}`}
          </Descriptions.Item>
          <Descriptions.Item label="币种">{order.currency}</Descriptions.Item>
          <Descriptions.Item label="来源销售单">
            {order.source_sales_order_no ? (
              // 无 sales:read(销售单段路由门)→ 降级纯文本(如将来入库仓库角色)。DESIGN §7。
              <Can
                perm={Permissions.SALES_READ}
                fallback={<span>{order.source_sales_order_no}</span>}
              >
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  onClick={() => router.push(`/sales/orders/${order.source_sales_order_id}`)}
                >
                  {order.source_sales_order_no}
                </Button>
              </Can>
            ) : (
              "—"
            )}
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <StatusTag meta={PURCHASE_ORDER_STATUS_META} value={order.status} />
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            {order.remark || "—"}
          </Descriptions.Item>
          {/* 🔴 成本红线:无 purchase:read_cost 者整项不渲染 */}
          {canSeeCost && (
            <Descriptions.Item label="金额" span={2}>
              <span style={{ fontWeight: 600 }}>
                {order.currency} {formatCost(order.total_amount)}
              </span>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Card title="采购明细">
        <Table<PurchaseOrderLineOut>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={lines}
          pagination={false}
          scroll={{ x: 1200 }}
        />
      </Card>

      <Card title="入库记录">
        <Table<RelatedInboundOrder>
          rowKey="id"
          size="small"
          columns={[
            {
              title: "入库单号",
              dataIndex: "no",
              width: 160,
              render: (v: string, r) => (
                // 无 inbound:read → 降级纯文本(单号可见,不可点)。DESIGN §7。
                <Can perm={Permissions.INBOUND_READ} fallback={<span>{v}</span>}>
                  <Button
                    type="link"
                    size="small"
                    style={{ padding: 0 }}
                    onClick={() => router.push(`/inbound/${r.id}`)}
                  >
                    {v}
                  </Button>
                </Can>
              ),
            },
            {
              title: "状态",
              dataIndex: "status",
              width: 100,
              render: (s: RelatedInboundOrder["status"]) => (
                <StatusTag meta={INBOUND_ORDER_STATUS_META} value={s} />
              ),
            },
            {
              title: "承运商 / 头程单号",
              key: "carrier",
              width: 200,
              render: (_, r) => {
                const parts = [r.carrier_name, r.tracking_no].filter(Boolean);
                return parts.length ? parts.join(" · ") : "—";
              },
            },
            { title: "预计到货", dataIndex: "eta", width: 120, render: (v: string | null) => v || "—" },
            { title: "实际到货", dataIndex: "arrived_at", width: 120, render: (v: string | null) => v || "—" },
            {
              title: "创建时间",
              dataIndex: "created_at",
              width: 170,
              render: (v: string) => formatDateTime(v),
            },
          ]}
          dataSource={inbounds}
          pagination={false}
          scroll={{ x: 870 }}
          locale={{ emptyText: "暂无入库记录" }}
        />
      </Card>

      <PurchaseOrderBuilder
        open={editing}
        mode="edit"
        sourceSalesOrderId={order.source_sales_order_id}
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
