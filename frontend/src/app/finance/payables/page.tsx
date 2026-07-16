"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { App, Button, Card, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";
import {
  PAYABLE_STATUS_META,
  formatAmount,
  payableApi,
  type PayableListItem,
} from "@/lib/payable";
import { colors } from "@/lib/tokens";

// 币种可选值(ISO4217,与供应商/采购口径一致)。
const CURRENCIES = ["USD", "CNY", "KES", "TZS", "EUR"];

export default function PayableListPage() {
  const router = useRouter();
  const { message } = App.useApp();

  const [rows, setRows] = useState<PayableListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
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
  }, [supplierId, currency, page, message]);

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
    { title: "币种", dataIndex: "currency", width: 70 },
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
    <Card title="应付款">
      <Space style={{ marginBottom: 16, width: "100%" }} wrap>
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
        <Select
          allowClear
          placeholder="币种"
          style={{ width: 120 }}
          value={currency}
          onChange={(v) => {
            setCurrency(v);
            setPage(1);
          }}
          options={CURRENCIES.map((c) => ({ value: c, label: c }))}
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
