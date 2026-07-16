"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { App, Button, Card, Input, Segmented, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";
import {
  PAYABLE_STATUS_META,
  formatAmount,
  payableApi,
  type PayableListItem,
  type PayableStatus,
} from "@/lib/payable";
import { colors } from "@/lib/tokens";
import { CURRENCIES } from "@/lib/currencies";

// 状态 tabs:全部 + 三派生态(DESIGN §7 工具条统一次序:状态最左)。
const STATUS_TABS = [
  { label: "全部", value: "" },
  ...Object.entries(PAYABLE_STATUS_META).map(([v, m]) => ({ label: m.label, value: v })),
];

export default function PayableListPage() {
  const router = useRouter();
  const { message } = App.useApp();

  const [rows, setRows] = useState<PayableListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined);
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [suppliers, setSuppliers] = useState<SupplierListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await payableApi.list({
        supplier_id: supplierId,
        currency: currency || undefined,
        status: (status || undefined) as PayableStatus | undefined,
        q: keyword.trim() || undefined,
        page,
        size: 20,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      setLoadError(true);
      message.error(e instanceof Error ? e.message : "加载应付款列表失败");
    } finally {
      setLoading(false);
    }
  }, [supplierId, currency, status, keyword, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  // 供应商筛选下拉(需 supplier:read;无权则下拉留空,不阻断币种筛选)。
  useEffect(() => {
    supplierApi
      .list({ size: 100 })
      .then((res) => setSuppliers(res.items))
      .catch(() => undefined);
  }, []);

  const columns: ColumnsType<PayableListItem> = [
    { title: "供应商", dataIndex: "supplier_display", width: 170, ellipsis: true },
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
            onClick={() => router.push(`/inbound/${r.inbound_order_id}`)}
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
            onClick={() => router.push(`/purchasing/orders/${r.purchase_order_id}`)}
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
      render: (s: PayableListItem["status"]) => {
        const m = PAYABLE_STATUS_META[s];
        return <Tag color={m.color}>{m.label}</Tag>;
      },
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
      render: (v: string) => v?.replace("T", " ").slice(0, 16),
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
        <div style={{ textAlign: "center", padding: "48px 0", color: colors.muted }}>
          加载失败
          <div style={{ marginTop: 12 }}>
            <Button onClick={load}>重试</Button>
          </div>
        </div>
      ) : (
        <Table<PayableListItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 1230 }}
          locale={{ emptyText: "暂无应付款" }}
          onChange={(_, filters) => {
            // 列头币种筛选 → 服务端过滤(filters.currency 单选)。
            const c = (filters.currency?.[0] as string) || undefined;
            if (c !== currency) {
              setCurrency(c);
              setPage(1);
            }
          }}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: setPage,
          }}
        />
      )}
    </Card>
  );
}
