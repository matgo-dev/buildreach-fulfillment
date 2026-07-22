"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
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
import { ListErrorState } from "@/components/common/ListErrorState";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";
import { formatDateTime } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import {
  PAYABLE_STATUS_META,
  formatAmount,
  payableApi,
  type PayableDetail,
  type PayableListItem,
  type PayableStatus,
} from "@/lib/payable";
import { CURRENCIES } from "@/lib/currencies";

// 状态 tabs:全部 + 三派生态(DESIGN §7 工具条统一次序:状态最左)。
const STATUS_TABS = [
  { label: "全部", value: "" },
  ...Object.entries(PAYABLE_STATUS_META).map(([v, m]) => ({ label: m.label, value: v })),
];

export default function PayableListPage() {
  const router = useRouter();
  const { message } = App.useApp();

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined);
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [suppliers, setSuppliers] = useState<SupplierListItem[]>([]);

  // 行下钻抽屉:账头 + 核销记录(哪笔付款冲了多少)。🔴整体在 payable:read 门控内。
  const [detail, setDetail] = useState<PayableDetail | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  // 「有未分配余额」标记只在列表行下发(详情端点不含),点行时随手带入抽屉。
  const [hasUnalloc, setHasUnalloc] = useState(false);

  async function openDetail(row: PayableListItem) {
    setDetailOpen(true);
    setDetailLoading(true);
    setDetail(null);
    setHasUnalloc(row.counterparty_has_unallocated);
    try {
      setDetail(await payableApi.get(row.id));
    } catch (e) {
      message.error(resolveBizError(e, "加载应付款详情失败"));
      setDetailOpen(false);
    } finally {
      setDetailLoading(false);
    }
  }

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      payableApi.list({
        supplier_id: supplierId,
        currency: currency || undefined,
        status: (status || undefined) as PayableStatus | undefined,
        q: keyword.trim() || undefined,
        page,
        size,
      }),
    [supplierId, currency, status, keyword],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<PayableListItem>(
    fetcher,
    { errorMessage: "加载应付款列表失败" },
  );

  // 供应商筛选下拉(需 supplier:read;无权则下拉留空,不阻断币种筛选)。
  useEffect(() => {
    supplierApi
      .list({ size: 100 })
      .then((res) => setSuppliers(res.items))
      .catch(() => undefined);
  }, []);

  const columns: ColumnsType<PayableListItem> = [
    {
      title: "供应商",
      dataIndex: "supplier_display",
      width: 200,
      ellipsis: true,
      render: (v: string, r) => (
        <Space size={4}>
          <span>{v}</span>
          {/* 该供应商有未分配付款余额 → 提示可用余额核销(下钻抽屉内一键入口)。 */}
          {r.counterparty_has_unallocated && <Tag color="warning">有未分配余额</Tag>}
        </Space>
      ),
    },
    {
      title: "入库单号",
      dataIndex: "inbound_order_no",
      width: 160,
      render: (v: string, r) => (
        // 无 inbound:read → 降级纯文本。DESIGN §7 单据链接降级。
        <Can perm={Permissions.INBOUND_READ} fallback={<span>{v}</span>}>
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/inbound/${r.inbound_order_id}`);
            }}
          >
            {v}
          </Button>
        </Can>
      ),
    },
    {
      title: "采购单号",
      dataIndex: "purchase_order_no",
      width: 160,
      render: (v: string, r) => (
        <Can perm={Permissions.PURCHASE_READ} fallback={<span>{v}</span>}>
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/purchasing/orders/${r.purchase_order_id}`);
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
      filters: CURRENCIES.map((c) => ({ text: c, value: c })),
      filterMultiple: false,
      filteredValue: currency ? [currency] : null,
    },
    {
      title: "应付金额",
      dataIndex: "amount_original",
      width: 130,
      align: "right",
      render: (v: number | string) => formatAmount(v),
    },
    {
      title: "已核销",
      dataIndex: "amount_allocated",
      width: 120,
      align: "right",
      render: (v: number | string) => formatAmount(v),
    },
    {
      title: "余额",
      dataIndex: "balance",
      width: 130,
      align: "right",
      render: (v: number | string) => <span style={{ fontWeight: 600 }}>{formatAmount(v)}</span>,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: PayableListItem["status"]) => <StatusTag meta={PAYABLE_STATUS_META} value={s} />,
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
    // 标题由面包屑承担(财务/应付款),Card 不重复
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
          placeholder="入库单号 / 采购单号 / 供应商名"
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
          placeholder="供应商"
          optionFilterProp="label"
          style={{ width: 220 }}
          value={supplierId}
          onChange={(v) => {
            setSupplierId(v);
            setPage(1);
          }}
          options={suppliers.map((s) => ({ value: s.id, label: `${s.code} · ${s.name}` }))}
        />
      </Space>

      {loadError && !rows.length ? (
        <ListErrorState onRetry={load} />
      ) : (
        <Table<PayableListItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 1290 }}
          locale={{ emptyText: "暂无应付款" }}
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

      {/* 行下钻抽屉:账头 + 核销记录(哪笔付款冲了多少)+ 用余额核销一键入口。🔴红线域。 */}
      <Drawer
        title={detail ? `应付款 ${detail.inbound_order_no}` : "应付款详情"}
        width={640}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
        loading={detailLoading}
        extra={
          detail &&
          hasUnalloc &&
          detail.status !== "PAID" && (
            // D10:该供应商有未分配付款 → 一键入口。跳转付款单页并预筛该供应商,不做复杂联动。
            <Can perm={Permissions.PAYMENT_MANAGE}>
              <Button
                type="primary"
                onClick={() => router.push(`/finance/payments?supplier_id=${detail.supplier_id}`)}
              >
                用未分配付款核销
              </Button>
            </Can>
          )
        }
      >
        {detail && (
          <>
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="供应商">
                {detail.supplier_display || "—"}
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <StatusTag meta={PAYABLE_STATUS_META} value={detail.status} />
              </Descriptions.Item>
              <Descriptions.Item label="币种">{detail.currency}</Descriptions.Item>
              <Descriptions.Item label="入库单号">{detail.inbound_order_no}</Descriptions.Item>
              <Descriptions.Item label="应付金额">
                {formatAmount(detail.amount_original)} {detail.currency}
              </Descriptions.Item>
              <Descriptions.Item label="已核销">
                {formatAmount(detail.amount_allocated)} {detail.currency}
              </Descriptions.Item>
              <Descriptions.Item label="余额" span={2}>
                <Typography.Text strong>
                  {formatAmount(detail.balance)} {detail.currency}
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
                { title: "付款单号", dataIndex: "payment_no", width: 170 },
                {
                  title: "金额",
                  dataIndex: "amount",
                  width: 130,
                  align: "right",
                  render: (v: number) => formatAmount(v),
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
    </Card>
  );
}
