"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Input,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { selectFilter } from "@/components/common/SelectFilter";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { customerApi, type CustomerListItem } from "@/lib/customer";
import { formatDateTime, formatMoney } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  RECEIVABLE_STATUS_META,
  receivableApi,
  type ReceivableDetail,
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
  const { message } = App.useApp();

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [customerId, setCustomerId] = useState<number | undefined>(undefined);
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [customers, setCustomers] = useState<CustomerListItem[]>([]);

  // 行下钻抽屉:账头 + 核销记录(哪笔收款冲了多少)。
  const [detail, setDetail] = useState<ReceivableDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  // 「有未分配收款」标记只在列表行下发(详情端点不含),点行时随手带入抽屉。
  const [hasUnalloc, setHasUnalloc] = useState(false);

  async function openDetail(row: ReceivableListItem) {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    setHasUnalloc(row.counterparty_has_unallocated);
    try {
      setDetail(await receivableApi.get(row.id));
    } catch (e) {
      message.error(resolveBizError(e, "加载应收款详情失败"));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }

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
    {
      title: "客户",
      dataIndex: "customer_display",
      width: 200,
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          <span>{v}</span>
          {/* 该客户有未分配收款 → 提示可核销(下钻抽屉内一键入口)。 */}
          {r.counterparty_has_unallocated && <Tag color="warning">有未分配收款</Tag>}
        </Space>
      ),
    },
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
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/outbound/${r.outbound_order_id}`);
            }}
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
      title: "币种",
      dataIndex: "currency",
      width: 90,
      // 次要枚举走列头筛选(DESIGN §7),服务端过滤;单选(核销要求同币种,多选无场景)。
      ...selectFilter<ReceivableListItem>(CURRENCIES.map((c) => ({ text: c, value: c }))),
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
      title: "未结应收",
      dataIndex: "amount_outstanding",
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
    <ListPageCard>
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

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<ReceivableListItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 1290 }}
            locale={{ emptyText: "暂无应收款" }}
            onChange={(_, filters) => {
              // 列头币种筛选 → 服务端过滤(filters.currency 单选)。
              const c = (filters.currency?.[0] as string) || undefined;
              if (c !== currency) {
                setCurrency(c);
                setPage(1);
              }
            }}
            onRow={(row) => ({
              onClick: () => openDetail(row),
              style: { cursor: "pointer" },
            })}
            pagination={pagination}
          />
        )}
      </ListPageBody>

      {/* 行下钻抽屉:账头 + 核销记录(哪笔收款冲了多少)+ 用未分配收款核销入口。 */}
      <Drawer
        title={detail ? `应收款 ${detail.outbound_order_no}` : "应收款详情"}
        size={640}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        loading={detailLoading}
        extra={
          detail &&
          hasUnalloc &&
          detail.status !== "PAID" && (
            // D10:该客户有未分配收款 → 一键入口。跳转收款单页并预筛该客户,不做复杂联动。
            <Can perm={Permissions.RECEIPT_MANAGE}>
              <Button
                type="primary"
                onClick={() => router.push(`/finance/receipts?customer_id=${detail.customer_id}`)}
              >
                用未分配收款核销
              </Button>
            </Can>
          )
        }
      >
        {detail && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="客户">{detail.customer_display || "—"}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <StatusTag meta={RECEIVABLE_STATUS_META} value={detail.status} />
              </Descriptions.Item>
              <Descriptions.Item label="币种">{detail.currency}</Descriptions.Item>
              <Descriptions.Item label="出库单号">{detail.outbound_order_no}</Descriptions.Item>
              <Descriptions.Item label="应收金额">
                {formatMoney(detail.amount_original)} {detail.currency}
              </Descriptions.Item>
              <Descriptions.Item label="已核销">
                {formatMoney(detail.amount_allocated)} {detail.currency}
              </Descriptions.Item>
              <Descriptions.Item label="未结应收" span={2}>
                <Typography.Text strong>
                  {formatMoney(detail.amount_outstanding)} {detail.currency}
                </Typography.Text>
              </Descriptions.Item>
            </Descriptions>

            <Typography.Title level={5} style={{ marginTop: 20 }}>
              核销记录
            </Typography.Title>
            <Table
              rowKey="id"
              size="small"
              dataSource={detail.allocations}
              pagination={false}
              locale={{ emptyText: "暂无核销记录" }}
              columns={[
                { title: "收款单号", dataIndex: "receipt_no", width: 170 },
                {
                  title: "金额",
                  dataIndex: "amount",
                  width: 130,
                  align: "right",
                  render: (v: number) => formatMoney(v),
                },
                {
                  title: "类型",
                  dataIndex: "alloc_type",
                  width: 80,
                  render: (v: string) => (v === "AUTO" ? "自动" : "人工"),
                },
                {
                  title: "核销时间",
                  dataIndex: "created_at",
                  width: 160,
                  render: (v: string) => formatDateTime(v),
                },
              ]}
            />
          </>
        )}
      </Drawer>
    </ListPageCard>
  );
}
