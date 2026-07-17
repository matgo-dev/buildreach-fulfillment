"use client";
import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { App, Button, Card, Drawer, Input, Popconfirm, Segmented, Space, Switch, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { FileAddOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListErrorState } from "@/components/common/ListErrorState";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { useAuthStore } from "@/stores/authStore";
import { formatDateTime, formatMoney } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import { quotationApi, type QuotationListItem } from "@/lib/quotation";
import { salesOrderApi, type SalesOrderListItem } from "@/lib/salesOrder";
import { SALES_ORDER_STATUS_META } from "@/lib/salesOrderStatus";
import { PURCHASE_PROGRESS_META } from "@/lib/purchaseOrderStatus";
import { colors } from "@/lib/tokens";

// 采购进度筛选(采购工作台「未下齐」队列)。次要枚举走列头筛选(DESIGN §7)。
const PROGRESS_FILTERS = [
  { value: "NOT_ORDERED", text: "未下单" },
  { value: "PARTIALLY_ORDERED", text: "部分下单" },
  { value: "FULLY_ORDERED", text: "已全部下单" },
];

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "已确认", value: "CONFIRMED" },
  { label: "已取消", value: "CANCELLED" },
];

export default function SalesOrderListPage() {
  const router = useRouter();
  const { message } = App.useApp();
  const userId = useAuthStore((s) => s.user?.id);

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [purchaseProgress, setPurchaseProgress] = useState("");
  const [mineOnly, setMineOnly] = useState(false);
  const [sort, setSort] = useState<"created_at" | "total_amount">("created_at");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [quoteDrawerOpen, setQuoteDrawerOpen] = useState(false);
  const [quoteKeyword, setQuoteKeyword] = useState("");
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteRows, setQuoteRows] = useState<QuotationListItem[]>([]);
  const [selectedQuoteId, setSelectedQuoteId] = useState<number | null>(null);
  const [converting, setConverting] = useState(false);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      salesOrderApi.list({
        status: status || undefined,
        no: keyword.trim() || undefined,
        purchase_progress: purchaseProgress || undefined,
        salesperson_id: mineOnly && userId ? userId : undefined,
        sort,
        dir: sortDir,
        page,
        size,
      }),
    [status, keyword, purchaseProgress, mineOnly, userId, sort, sortDir],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<SalesOrderListItem>(
    fetcher,
    { errorMessage: "加载销售单列表失败" },
  );

  const loadLockedQuotations = useCallback(async (keyword = quoteKeyword) => {
    setQuoteLoading(true);
    try {
      const res = await quotationApi.list({
        status: "LOCKED",
        keyword: keyword || undefined,
        sort: "created_at",
        page: 1,
        size: 100,
      });
      setQuoteRows(res.items);
      setSelectedQuoteId(null);
    } catch (e) {
      message.error(resolveBizError(e, "加载锁档报价失败"));
    } finally {
      setQuoteLoading(false);
    }
  }, [message, quoteKeyword]);

  async function openQuoteDrawer() {
    setQuoteKeyword("");
    setQuoteDrawerOpen(true);
    await loadLockedQuotations("");
  }

  async function onConvertSelected() {
    if (!selectedQuoteId) return;
    setConverting(true);
    try {
      const { order } = await quotationApi.convert(selectedQuoteId);
      message.success(`已生成销售单 ${order.no}`);
      setQuoteDrawerOpen(false);
      await load();
      router.push(`/sales/orders/${order.id}`);
    } catch (e) {
      message.error(resolveBizError(e, "生成销售单失败"));
    } finally {
      setConverting(false);
    }
  }

  const columns: ColumnsType<SalesOrderListItem> = [
    { title: "单号", dataIndex: "no", width: 150 },
    { title: "客户", dataIndex: "customer_display", width: 160, ellipsis: true },
    { title: "报价人", dataIndex: "salesperson_display", width: 100 },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (s: SalesOrderListItem["status"]) => <StatusTag meta={SALES_ORDER_STATUS_META} value={s} />,
    },
    {
      title: "采购进度",
      dataIndex: "purchase_progress",
      width: 110,
      filters: PROGRESS_FILTERS,
      filterMultiple: false,
      filteredValue: purchaseProgress ? [purchaseProgress] : null,
      render: (p: SalesOrderListItem["purchase_progress"]) =>
        p ? <StatusTag meta={PURCHASE_PROGRESS_META} value={p} /> : "—",
    },
    { title: "币种", dataIndex: "currency", width: 70 },
    {
      title: "总额",
      dataIndex: "total_amount",
      width: 120,
      align: "right",
      sorter: true,
      render: (v) => formatMoney(v),
    },
    { title: "行数", dataIndex: "line_count", width: 70, align: "right" },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
  ];

  const quotationColumns: ColumnsType<QuotationListItem> = [
    { title: "报价单号", dataIndex: "no", width: 140 },
    { title: "客户", dataIndex: "customer_display", ellipsis: true },
    { title: "报价人", dataIndex: "salesperson_display", width: 100 },
    {
      title: "金额",
      key: "amount",
      width: 120,
      align: "right",
      render: (_, r) => `${r.currency} ${formatMoney(r.total_amount)}`,
    },
    { title: "创建时间", dataIndex: "created_at", width: 150, render: (v: string) => formatDateTime(v) },
  ];

  const selectedQuote = useMemo(
    () => quoteRows.find((r) => r.id === selectedQuoteId) ?? null,
    [quoteRows, selectedQuoteId],
  );

  return (
    <Card>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }} wrap>
        <Space wrap>
          <Segmented
            options={STATUS_TABS}
            value={status}
            onChange={(v) => {
              setStatus(v as string);
              setPage(1);
            }}
          />
          <Input.Search
            placeholder="销售单号"
            allowClear
            style={{ width: 220 }}
            onSearch={(v) => {
              setKeyword(v);
              setPage(1);
            }}
          />
          <span>
            <Switch
              size="small"
              checked={mineOnly}
              onChange={(c) => {
                setMineOnly(c);
                setPage(1);
              }}
            />{" "}
            报价人=我
          </span>
        </Space>
        <Can perm={Permissions.QUOTE_MANAGE}>
          <Button type="primary" icon={<FileAddOutlined />} onClick={openQuoteDrawer}>
            从报价生成
          </Button>
        </Can>
      </Space>
      {loadError && !rows.length ? (
        <ListErrorState onRetry={load} />
      ) : (
        <Table<SalesOrderListItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 1120 }}
          locale={{ emptyText: "暂无销售单" }}
          onRow={(r) => ({
            onClick: () => router.push(`/sales/orders/${r.id}`),
            style: { cursor: "pointer" },
          })}
          pagination={pagination}
          onChange={(_p, filters, sorter) => {
            const s = Array.isArray(sorter) ? sorter[0] : sorter;
            setSort(s?.field === "total_amount" ? "total_amount" : "created_at");
            setSortDir(s?.order === "ascend" ? "asc" : "desc");
            // 列头采购进度筛选 → 服务端过滤(单选)。
            const p = (filters.purchase_progress?.[0] as string) || "";
            if (p !== purchaseProgress) {
              setPurchaseProgress(p);
              setPage(1);
            }
          }}
        />
      )}
      <Drawer
        title="从锁档报价生成销售单"
        open={quoteDrawerOpen}
        onClose={() => setQuoteDrawerOpen(false)}
        width="min(760px, 92vw)"
        destroyOnClose
        footer={
          <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
            <span style={{ color: colors.muted }}>
              {selectedQuote
                ? `已选择 ${selectedQuote.no} · ${selectedQuote.customer_display} · ${selectedQuote.currency} ${formatMoney(selectedQuote.total_amount)}`
                : "选择一张锁档报价作为销售单来源"}
            </span>
            <Space>
              <Button onClick={() => setQuoteDrawerOpen(false)} disabled={converting}>
                取消
              </Button>
              <Popconfirm
                title="生成销售单?"
                description="生成后该报价进入已转销售终态,不可撤回。"
                okText="确认生成"
                okButtonProps={{ danger: true, loading: converting }}
                onConfirm={onConvertSelected}
              >
                <Button type="primary" danger disabled={!selectedQuoteId} loading={converting}>
                  生成销售单
                </Button>
              </Popconfirm>
            </Space>
          </Space>
        }
      >
        <Input.Search
          placeholder="搜索报价单号 / 客户名"
          allowClear
          value={quoteKeyword}
          style={{ width: 360, maxWidth: "100%", marginBottom: 16 }}
          onChange={(e) => setQuoteKeyword(e.target.value)}
          onSearch={(v) => {
            setQuoteKeyword(v);
            loadLockedQuotations(v);
          }}
        />
        <Table<QuotationListItem>
          rowKey="id"
          size="small"
          columns={quotationColumns}
          dataSource={quoteRows}
          loading={quoteLoading}
          pagination={{ pageSize: 8, showSizeChanger: false }}
          scroll={{ x: 680 }}
          locale={{ emptyText: "暂无可生成销售单的锁档报价" }}
          rowSelection={{
            type: "radio",
            selectedRowKeys: selectedQuoteId ? [selectedQuoteId] : [],
            onChange: (keys) => setSelectedQuoteId(Number(keys[0])),
          }}
          onRow={(r) => ({
            onClick: () => setSelectedQuoteId(r.id),
            style: { cursor: "pointer" },
          })}
        />
      </Drawer>
    </Card>
  );
}
