"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { App, Button, Card, Input, Segmented, Select, Space, Table, Tag } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { PurchaseOrderBuilder } from "@/components/purchasing/PurchaseOrderBuilder";
import { SalesOrderPicker } from "@/components/purchasing/SalesOrderPicker";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";
import {
  formatCost,
  purchaseOrderApi,
  type PurchaseOrderListItem,
} from "@/lib/purchaseOrder";
import { PURCHASE_ORDER_STATUS_META } from "@/lib/purchaseOrderStatus";
import { RECEIPT_PROGRESS_META } from "@/lib/inboundOrderStatus";
import { InTransitBadge } from "@/components/inbound/InTransitBadge";
import { colors } from "@/lib/tokens";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "草稿", value: "DRAFT" },
  { label: "已确认", value: "CONFIRMED" },
  { label: "已取消", value: "CANCELLED" },
];

export default function PurchaseOrderListPage() {
  const router = useRouter();
  const search = useSearchParams();
  const { message } = App.useApp();
  const sourceSalesOrderId = search.get("source_sales_order_id");

  const [rows, setRows] = useState<PurchaseOrderListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined);
  const [soNo, setSoNo] = useState("");
  const [suppliers, setSuppliers] = useState<SupplierListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  // 建单 pull 入口:先选一张 SO(picker),选定后带 SO id 打开建单器。
  const [pickerOpen, setPickerOpen] = useState(false);
  const [builderSourceId, setBuilderSourceId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await purchaseOrderApi.list({
        status: status || undefined,
        supplier_id: supplierId,
        source_sales_order_id: sourceSalesOrderId ? Number(sourceSalesOrderId) : undefined,
        source_sales_order_no: soNo || undefined,
        page,
        size: 20,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      setLoadError(true);
      message.error(e instanceof Error ? e.message : "加载采购单列表失败");
    } finally {
      setLoading(false);
    }
  }, [status, supplierId, soNo, sourceSalesOrderId, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  // 供应商筛选下拉数据(启用+停用都要,便于筛历史)。
  useEffect(() => {
    supplierApi
      .list({ size: 100 })
      .then((res) => setSuppliers(res.items))
      .catch(() => undefined);
  }, []);

  const columns: ColumnsType<PurchaseOrderListItem> = [
    { title: "采购单号", dataIndex: "no", width: 160 },
    {
      title: "来源销售单",
      dataIndex: "source_sales_order_no",
      width: 150,
      render: (v: string | null, r) =>
        v ? (
          // 无 sales:read → 降级纯文本(DESIGN §7);fallback 也 stopPropagation,免点单号误触发行下钻。
          <Can
            perm={Permissions.SALES_READ}
            fallback={<span onClick={(e) => e.stopPropagation()}>{v}</span>}
          >
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={(e) => {
                e.stopPropagation();
                router.push(`/sales/orders/${r.source_sales_order_id}`);
              }}
            >
              {v}
            </Button>
          </Can>
        ) : (
          "—"
        ),
    },
    { title: "供应商", dataIndex: "supplier_display", width: 180, ellipsis: true },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: PurchaseOrderListItem["status"]) => {
        const m = PURCHASE_ORDER_STATUS_META[s];
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    { title: "币种", dataIndex: "currency", width: 70 },
    {
      title: "金额",
      dataIndex: "total_amount",
      width: 130,
      align: "right",
      render: (v) => formatCost(v),
    },
    { title: "行数", dataIndex: "line_count", width: 70, align: "right" },
    {
      title: "收货进度",
      dataIndex: "receipt_progress",
      width: 150,
      render: (p: PurchaseOrderListItem["receipt_progress"], r) => {
        // 收货进度(实收口径的语义徽标)+ 弱化在途信号,后者只回答「有货在路上」。
        const m = p ? RECEIPT_PROGRESS_META[p] : null;
        return (
          <Space size={4}>
            {m ? <Tag color={m.color}>{m.label}</Tag> : <span>—</span>}
            <InTransitBadge count={r.in_transit_count} />
          </Space>
        );
      },
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => v?.replace("T", " ").slice(0, 16),
    },
  ];

  return (
    <Card
      title="采购单"
      extra={
        <Can perm={Permissions.PURCHASE_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
            新建采购单
          </Button>
        </Can>
      }
    >
      <Space style={{ marginBottom: 16, width: "100%" }} wrap>
        <Segmented
          options={STATUS_TABS}
          value={status}
          onChange={(v) => {
            setStatus(v as string);
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
        <Input.Search
          allowClear
          placeholder="来源销售单号"
          style={{ width: 200 }}
          defaultValue={soNo}
          onSearch={(v) => {
            setSoNo(v.trim());
            setPage(1);
          }}
        />
        {sourceSalesOrderId && (
          <Button size="small" onClick={() => router.push("/purchasing/orders")}>
            清除来源销售单筛选
          </Button>
        )}
      </Space>

      {loadError && !rows.length ? (
        <div style={{ textAlign: "center", padding: "48px 0", color: colors.muted }}>
          加载失败
          <div style={{ marginTop: 12 }}>
            <Button onClick={load}>重试</Button>
          </div>
        </div>
      ) : (
        <Table<PurchaseOrderListItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 1170 }}
          locale={{ emptyText: "暂无采购单" }}
          onRow={(r) => ({
            onClick: () => router.push(`/purchasing/orders/${r.id}`),
            style: { cursor: "pointer" },
          })}
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

      {/* pull 入口:选 SO → 打开建单器。采购单恒绑单一 SO,故先选一张。 */}
      <SalesOrderPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPick={(soId) => {
          setPickerOpen(false);
          setBuilderSourceId(soId);
        }}
      />
      <PurchaseOrderBuilder
        open={builderSourceId !== null}
        mode="create"
        sourceSalesOrderId={builderSourceId ?? 0}
        onClose={() => setBuilderSourceId(null)}
        onSaved={() => {
          setBuilderSourceId(null);
          load();
        }}
      />
    </Card>
  );
}
