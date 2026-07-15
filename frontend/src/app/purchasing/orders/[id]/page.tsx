"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { App, Button, Card, Descriptions, Popconfirm, Space, Spin, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { formatQty } from "@/lib/salesOrder";
import {
  formatCost,
  purchaseErrorMessage,
  purchaseOrderApi,
  type PurchaseOrderLineOut,
  type PurchaseOrderOut,
} from "@/lib/purchaseOrder";
import {
  PURCHASE_ORDER_STATUS_META,
  purchaseOrderCancellable,
  purchaseOrderConfirmable,
  purchaseOrderDeletable,
  purchaseOrderEditable,
} from "@/lib/purchaseOrderStatus";
import { PurchaseOrderBuilder } from "@/components/purchasing/PurchaseOrderBuilder";

export default function PurchaseOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message } = App.useApp();
  const id = Number(params.id);

  const [order, setOrder] = useState<PurchaseOrderOut | null>(null);
  const [lines, setLines] = useState<PurchaseOrderLineOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { order: o, lines: ls } = await purchaseOrderApi.get(id);
      setOrder(o);
      setLines(ls);
    } catch (e) {
      message.error(purchaseErrorMessage(e, "加载失败"));
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
      message.error(purchaseErrorMessage(e, "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  async function onDelete() {
    setBusy(true);
    try {
      await purchaseOrderApi.del(id);
      message.success("已删除");
      router.push("/purchasing/orders");
    } catch (e) {
      message.error(purchaseErrorMessage(e, "删除失败"));
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
      { title: "采购价", dataIndex: "unit_price", width: 120, align: "right", render: formatCost },
      { title: "行额", dataIndex: "line_total", width: 130, align: "right", render: formatCost },
      { title: "备注", dataIndex: "remark", ellipsis: true, render: (v) => v || "—" },
    ],
    [],
  );

  if (loading || !order) return <Spin style={{ display: "block", marginTop: 80 }} />;

  const meta = PURCHASE_ORDER_STATUS_META[order.status];

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
            <Tag color={meta.color}>{meta.label}</Tag>
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
              {purchaseOrderDeletable(order.status) && (
                <Popconfirm
                  title="删除草稿?"
                  description="草稿将被永久删除,不可恢复。"
                  okButtonProps={{ danger: true }}
                  onConfirm={onDelete}
                >
                  <Button danger loading={busy}>
                    删除
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
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => router.push(`/sales/orders/${order.source_sales_order_id}`)}
              >
                {order.source_sales_order_no}
              </Button>
            ) : (
              "—"
            )}
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={meta.color}>{meta.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>
            {order.remark || "—"}
          </Descriptions.Item>
          <Descriptions.Item label="金额" span={2}>
            <span style={{ fontWeight: 600 }}>
              {order.currency} {formatCost(order.total_amount)}
            </span>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="采购明细">
        <Table<PurchaseOrderLineOut>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={lines}
          pagination={false}
          scroll={{ x: 960 }}
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
