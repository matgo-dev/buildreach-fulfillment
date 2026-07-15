"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { App, Button, Card, Descriptions, Space, Spin, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined } from "@ant-design/icons";
import {
  salesOrderApi,
  type SalesOrderLineOut,
  type SalesOrderOut,
} from "@/lib/salesOrder";
import { SALES_ORDER_STATUS_META } from "@/lib/salesOrderStatus";

function money(v: number | string) {
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 });
}

export default function SalesOrderDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { message } = App.useApp();
  const id = Number(params.id);

  const [order, setOrder] = useState<SalesOrderOut | null>(null);
  const [lines, setLines] = useState<SalesOrderLineOut[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { order: o, lines: ls } = await salesOrderApi.get(id);
      setOrder(o);
      setLines(ls);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [id, message]);

  useEffect(() => {
    load();
  }, [load]);

  const columns: ColumnsType<SalesOrderLineOut> = useMemo(
    () => [
      { title: "#", render: (_, __, i) => i + 1, width: 44 },
      { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
      { title: "规格", dataIndex: "spec_text_snapshot", ellipsis: true, render: (v) => v || "—" },
      { title: "单位", dataIndex: "unit_snapshot", width: 70 },
      { title: "数量", dataIndex: "qty", width: 90, align: "right", render: money },
      { title: "单价", dataIndex: "unit_price", width: 110, align: "right", render: money },
      { title: "金额", dataIndex: "line_total", width: 120, align: "right", render: money },
      { title: "备注", dataIndex: "remark", ellipsis: true, render: (v) => v || "—" },
    ],
    [],
  );

  if (loading || !order) return <Spin style={{ display: "block", marginTop: 80 }} />;

  const meta = SALES_ORDER_STATUS_META[order.status];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title={
          <Space size={8}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => router.push("/sales/orders")}
              aria-label="返回列表"
            />
            <span>{order.no}</span>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Space>
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="客户">
            {order.customer_display ?? `#${order.customer_id}`}
          </Descriptions.Item>
          <Descriptions.Item label="报价人">
            {order.salesperson_display ?? `#${order.salesperson_id}`}
          </Descriptions.Item>
          <Descriptions.Item label="币种">{order.currency}</Descriptions.Item>
          <Descriptions.Item label="来源报价">
            {order.source_quotation_no ? (
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={() => router.push(`/sales/quotations/${order.source_quotation_id}`)}
              >
                {order.source_quotation_no}
              </Button>
            ) : (
              "—"
            )}
          </Descriptions.Item>
          <Descriptions.Item label="摘要" span={2}>{order.summary || "—"}</Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>{order.remark || "—"}</Descriptions.Item>
          <Descriptions.Item label="总额" span={2}>
            <span style={{ fontWeight: 600 }}>
              {order.currency} {money(order.total_amount)}
            </span>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="销售明细">
        <Table<SalesOrderLineOut>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={lines}
          pagination={false}
          scroll={{ x: 900 }}
        />
      </Card>
    </Space>
  );
}
