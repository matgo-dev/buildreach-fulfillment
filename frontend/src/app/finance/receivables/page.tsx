"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Input, Segmented, Select, Space, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListErrorState } from "@/components/common/ListErrorState";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { customerApi, type CustomerListItem } from "@/lib/customer";
import { formatDateTime, formatMoney } from "@/lib/format";
import {
  RECEIVABLE_STATUS_META,
  receivableApi,
  type ReceivableListItem,
  type ReceivableStatus,
} from "@/lib/receivable";
import { CURRENCIES } from "@/lib/currencies";

// 状态 tabs:全部 + 三派生态(DESIGN §7 工具条统一次序:状态最左)。
const STATUS_TABS = [
  { label: "全部", value: "" },
  ...Object.entries(RECEIVABLE_STATUS_META).map(([v, m]) => ({ label: m.label, value: v })),
];

export default function ReceivableListPage() {
  const router = useRouter();

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [customerId, setCustomerId] = useState<number | undefined>(undefined);
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      receivableApi.list({
        customer_id: customerId,
        currency: currency || undefined,
        status: (status || undefined) as ReceivableStatus | undefined,
        q: keyword.trim() || undefined,
        page,
        size,
      }),
    [customerId, currency, status, keyword],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<ReceivableListItem>(
    fetcher,
    { errorMessage: "加载应收款列表失败" },
  );

  // 客户筛选下拉(需 customer:read;无权则下拉留空,不阻断币种筛选)。
  useEffect(() => {
    customerApi
      .list({ size: 100 })
      .then((res) => setCustomers(res.items))
      .catch(() => undefined);
  }, []);

  const columns: ColumnsType<ReceivableListItem> = [
    { title: "客户", dataIndex: "customer_display", width: 180, ellipsis: true },
    {
      title: "出库单号",
      dataIndex: "outbound_order_no",
      width: 160,
      render: (v: string, r) => (
        // 无 outbound:read → 降级纯文本。DESIGN §7 单据链接降级。
        <Can perm={Permissions.OUTBOUND_READ} fallback={<span>{v}</span>}>
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={() => router.push(`/outbound/${r.outbound_order_id}`)}
          >
            {v}
          </Button>
        </Can>
      ),
    },
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
            onClick={() => router.push(`/sales/orders/${r.sales_order_id}`)}
          >
            {v}
          </Button>
        </Can>
      ),
    },
    {
      title: "币种",
      dataIndex: "currency",
      width: 90,
      // 次要枚举走列头筛选(DESIGN §7),服务端过滤;单选(核销要求同币种,多选无场景)。
      filters: CURRENCIES.map((c) => ({ text: c, value: c })),
      filterMultiple: false,
      filteredValue: currency ? [currency] : null,
    },
    {
      title: "应收金额",
      dataIndex: "amount_original",
      width: 130,
      align: "right",
      render: (v: number | string) => formatMoney(v),
    },
    {
      title: "已核销",
      dataIndex: "amount_allocated",
      width: 120,
      align: "right",
      render: (v: number | string) => formatMoney(v),
    },
    {
      title: "余额",
      dataIndex: "balance",
      width: 130,
      align: "right",
      render: (v: number | string) => <span style={{ fontWeight: 600 }}>{formatMoney(v)}</span>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: ReceivableListItem["status"]) => (
        <StatusTag meta={RECEIVABLE_STATUS_META} value={s} />
      ),
    },
    {
      title: "到期日",
      dataIndex: "due_at",
      width: 120,
      render: (v: string | null) => v || "—",
    },
    {
      title: "生成时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
  ];

  return (
    // 标题由面包屑承担(财务/应收款),Card 不重复
    <Card>
      {/* 工具条统一次序(DESIGN §7):状态 Segmented → 搜索框 → 参照维度下拉。币种在列头。 */}
      <Space style={{ marginBottom: 16, width: "100%" }} wrap>
        <Segmented
          options={STATUS_TABS}
          value={status}
          onChange={(v) => {
            setStatus(v as string);
            setPage(1);
          }}
        />
        <Input.Search
          placeholder="出库单号 / 销售单号 / 客户名"
          allowClear
          style={{ width: 280 }}
          onSearch={(v) => {
            setKeyword(v);
            setPage(1);
          }}
        />
        <Select
          allowClear
          showSearch
          placeholder="客户"
          optionFilterProp="label"
          style={{ width: 220 }}
          value={customerId}
          onChange={(v) => {
            setCustomerId(v);
            setPage(1);
          }}
          options={customers.map((c) => ({ value: c.id, label: `${c.code} · ${c.name}` }))}
        />
      </Space>

      {loadError && !rows.length ? (
        <ListErrorState onRetry={load} />
      ) : (
        <Table<ReceivableListItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 1250 }}
          locale={{ emptyText: "暂无应收款" }}
          onChange={(_, filters) => {
            // 列头币种筛选 → 服务端过滤(filters.currency 单选)。
            const c = (filters.currency?.[0] as string) || undefined;
            if (c !== currency) {
              setCurrency(c);
              setPage(1);
            }
          }}
          pagination={pagination}
        />
      )}
    </Card>
  );
}
