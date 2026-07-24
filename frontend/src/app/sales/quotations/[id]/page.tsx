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
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { PageLoading } from "@/components/common/PageLoading";
import { ListErrorState } from "@/components/common/ListErrorState";
import { Permissions } from "@/config/permission-matrix";
import { QuotationEditor } from "@/components/quotation/QuotationEditor";
import { formatMoney } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  quotationApi,
  type QuotationLineOut,
  type QuotationOrderOut,
} from "@/lib/quotation";
import {
  QUOTATION_STATUS_META,
  quotationConvertible,
  quotationEditable,
  quotationLockable,
  quotationUnlockable,
  quotationVoidable,
} from "@/lib/quotationStatus";

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
  const [loadError, setLoadError] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const { order: o, lines: ls } = await quotationApi.get(id);
      setOrder(o);
      setLines(ls);
      // 展示名由详情响应服务端直出(不再靠"可选人列表"反查:历史报价人停用/改角色后仍显示姓名)。
      setCustomerName(o.customer_display ?? `#${o.customer_id}`);
      setSalespersonName(o.salesperson_display ?? `#${o.salesperson_id}`);
    } catch (e) {
      setLoadError(true);
      message.error(resolveBizError(e, "加载失败"));
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
      message.error(resolveBizError(e, "操作失败"));
    } finally {
      setBusy(false);
    }
  }

  // 转销售:成功后跳新建的销售单详情(不停留在已终态的报价)。
  async function onConvert() {
    setBusy(true);
    try {
      const { order: so } = await quotationApi.convert(id);
      message.success(`已转销售单 ${so.no}`);
      router.push(`/sales/orders/${so.id}`);
    } catch (e) {
      message.error(resolveBizError(e, "转销售失败"));
      setBusy(false);
    }
  }

  const columns: ColumnsType<QuotationLineOut> = useMemo(
    () => [
      { title: "#", render: (_, __, i) => i + 1, width: 44 },
      { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
      { title: "规格", dataIndex: "spec_text_snapshot", ellipsis: true, render: (v) => v || "—" },
      { title: "单位", dataIndex: "unit_snapshot", width: 70 },
      { title: "数量", dataIndex: "qty", width: 90, align: "right", render: formatMoney },
      { title: "单价", dataIndex: "unit_price", width: 110, align: "right", render: formatMoney },
      { title: "金额", dataIndex: "line_total", width: 120, align: "right", render: formatMoney },
      { title: "备注", dataIndex: "remark", ellipsis: true, render: (v) => v || "—" },
    ],
    [],
  );

  if (isEdit) return <QuotationEditor mode="edit" orderId={id} />;
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
              onClick={() => router.push("/sales/quotations")}
              aria-label="返回列表"
            />
            <span>{order.no}</span>
            <StatusTag meta={QUOTATION_STATUS_META} value={order.status} />
          </Space>
        }
        extra={
          <Space>
            {/* 已转销售:只读出口,跳生成的销售单(反查字段 order.sales_order)。 */}
            {order.status === "CONVERTED" && order.sales_order && (
              <Button type="link" onClick={() => router.push(`/sales/orders/${order.sales_order!.id}`)}>
                查看销售单 {order.sales_order.no}
              </Button>
            )}
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
                {quotationConvertible(order.status) && (
                  <Popconfirm
                    title="转为销售单?"
                    description="转换后此报价锁定为「已转销售」终态、不可撤回,并生成一张销售单。"
                    okText="确认转销售"
                    okButtonProps={{ danger: true }}
                    onConfirm={onConvert}
                  >
                    <Button type="primary" danger loading={busy}>转销售单</Button>
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
          </Space>
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
              {order.currency} {formatMoney(order.total_amount)}
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
