"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  App,
  Button,
  Card,
  Descriptions,
  Popconfirm,
  Space,
  Spin,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { QuotationEditor } from "@/components/quotation/QuotationEditor";
import {
  quotationApi,
  type QuotationLineOut,
  type QuotationOrderOut,
} from "@/lib/quotation";
import {
  QUOTATION_STATUS_META,
  quotationEditable,
  quotationLockable,
  quotationUnlockable,
  quotationVoidable,
} from "@/lib/quotationStatus";

function money(v: number | string) {
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 });
}

export default function QuotationDetailPage() {
  const params = useParams();
  const search = useSearchParams();
  const router = useRouter();
  const { message } = App.useApp();
  const id = Number(params.id);
  const isEdit = search.get("edit") === "1";

  const [order, setOrder] = useState<QuotationOrderOut | null>(null);
  const [lines, setLines] = useState<QuotationLineOut[]>([]);
  const [customerName, setCustomerName] = useState("");
  const [salespersonName, setSalespersonName] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { order: o, lines: ls } = await quotationApi.get(id);
      setOrder(o);
      setLines(ls);
      // 展示名由详情响应服务端直出(不再靠"可选人列表"反查:历史报价人停用/改角色后仍显示姓名)。
      setCustomerName(o.customer_display ?? `#${o.customer_id}`);
      setSalespersonName(o.salesperson_display ?? `#${o.salesperson_id}`);
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [id, message]);

  useEffect(() => {
    if (!isEdit) load();
  }, [isEdit, load]);

  async function act(fn: () => Promise<unknown>, ok: string) {
    setBusy(true);
    try {
      await fn();
      message.success(ok);
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnsType<QuotationLineOut> = useMemo(
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

  if (isEdit) return <QuotationEditor mode="edit" orderId={id} />;
  if (loading || !order) return <Spin style={{ display: "block", marginTop: 80 }} />;

  const meta = QUOTATION_STATUS_META[order.status];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title={
          <Space size={8}>
            <Button
              type="text"
              size="small"
              icon={<ArrowLeftOutlined />}
              onClick={() => router.push("/sales/quotations")}
              aria-label="返回列表"
            />
            <span>{order.no}</span>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Space>
        }
        extra={
          <Can perm={Permissions.QUOTE_MANAGE}>
            <Space>
              {quotationEditable(order.status) && (
                <Button onClick={() => router.push(`/sales/quotations/${id}?edit=1`)}>编辑</Button>
              )}
              {quotationLockable(order.status) && (
                <Button type="primary" loading={busy} onClick={() => act(() => quotationApi.lock(id), "已锁档")}>
                  锁档
                </Button>
              )}
              {quotationUnlockable(order.status) && (
                <Popconfirm title="撤回锁档,回到草稿?" onConfirm={() => act(() => quotationApi.unlock(id), "已撤回")}>
                  <Button loading={busy}>撤回锁档</Button>
                </Popconfirm>
              )}
              {quotationVoidable(order.status) && (
                <Popconfirm
                  title="作废该报价?"
                  description="作废后不可编辑,可留档备查。"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => act(() => quotationApi.void(id), "已作废")}
                >
                  <Button danger loading={busy}>作废</Button>
                </Popconfirm>
              )}
            </Space>
          </Can>
        }
      >
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label="客户">{customerName}</Descriptions.Item>
          <Descriptions.Item label="报价人">{salespersonName}</Descriptions.Item>
          <Descriptions.Item label="币种">{order.currency}</Descriptions.Item>
          <Descriptions.Item label="有效期">{order.valid_until || "—"}</Descriptions.Item>
          <Descriptions.Item label="摘要" span={2}>{order.summary || "—"}</Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>{order.remark || "—"}</Descriptions.Item>
          <Descriptions.Item label="总额" span={2}>
            <span style={{ fontWeight: 600 }}>
              {order.currency} {money(order.total_amount)}
            </span>
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="报价明细">
        <Table<QuotationLineOut>
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
