"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button, Input, Segmented, Select, Space } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ProgressCell } from "@/components/common/ProgressCell";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { useAuthStore } from "@/stores/authStore";
import { PurchaseOrderBuilder } from "@/components/purchasing/PurchaseOrderBuilder";
import { SalesOrderPicker } from "@/components/purchasing/SalesOrderPicker";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";
import { formatDateTime } from "@/lib/format";
import {
  formatCost,
  purchaseOrderApi,
  type PurchaseOrderListItem,
} from "@/lib/purchaseOrder";
import { PURCHASE_ORDER_STATUS_META } from "@/lib/purchaseOrderStatus";
import { RECEIPT_PROGRESS_META } from "@/lib/inboundOrderStatus";
import { InTransitBadge } from "@/components/inbound/InTransitBadge";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "草稿", value: "DRAFT" },
  { label: "已确认", value: "CONFIRMED" },
  { label: "已取消", value: "CANCELLED" },
];

export default function PurchaseOrderListPage() {
  // 🔴 成本红线可见性:无权者后端已脱敏,渲染层整列藏掉(DESIGN.md §9)。
  const canSeeCost = useAuthStore((s) => s.hasPermission(Permissions.PURCHASE_READ_COST));
  const router = useRouter();
  const search = useSearchParams();
  const sourceSalesOrderId = search.get("source_sales_order_id");

  const [status, setStatus] = useState("");
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined);
  const [soNo, setSoNo] = useState("");
  const [suppliers, setSuppliers] = useState<SupplierListItem[]>([]);
  // 建单 pull 入口:先选一张 SO(picker),选定后带 SO id 打开建单器。
  const [pickerOpen, setPickerOpen] = useState(false);
  const [builderSourceId, setBuilderSourceId] = useState<number | null>(null);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      purchaseOrderApi.list({
        status: status || undefined,
        supplier_id: supplierId,
        source_sales_order_id: sourceSalesOrderId ? Number(sourceSalesOrderId) : undefined,
        source_sales_order_no: soNo || undefined,
        page,
        size,
      }),
    [status, supplierId, soNo, sourceSalesOrderId],
  );
  const { rows, setPage, loading, loadError, load, pagination } =
    useListQuery<PurchaseOrderListItem>(fetcher, { errorMessage: "加载采购单列表失败" });

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
      title: "单据状态",
      dataIndex: "status",
      width: 100,
      render: (s: PurchaseOrderListItem["status"]) => (
        <StatusTag meta={PURCHASE_ORDER_STATUS_META} value={s} />
      ),
    },
    { title: "币种", dataIndex: "currency", width: 70 },
    // 🔴 成本红线:无 purchase:read_cost 者整列不渲染(DESIGN.md §9);render 仍走 formatCost 兜漂移。
    ...((canSeeCost
      ? [
          {
            title: "金额",
            dataIndex: "total_amount",
            width: 130,
            align: "right",
            render: (v) => formatCost(v),
          },
        ]
      : []) as ColumnsType<PurchaseOrderListItem>),
    { title: "行数", dataIndex: "line_count", width: 70, align: "right" },
    {
      title: "收货进度",
      dataIndex: "receipt_progress",
      width: 180,
      render: (p: PurchaseOrderListItem["receipt_progress"], r) => (
        // 收货进度(实收口径的语义徽标)+ 弱化在途信号,后者只回答「有货在路上」。
        <Space size={4}>
          {p ? <ProgressCell meta={RECEIPT_PROGRESS_META} value={p} /> : <span>—</span>}
          <InTransitBadge count={r.in_transit_count} />
        </Space>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (v: string) => formatDateTime(v),
    },
  ];

  return (
    <ListPageCard>
      {/* 工具条统一次序(DESIGN §7):状态 → 搜索 → 参照维度;标题由面包屑承担,不重复。 */}
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
            allowClear
            placeholder="来源销售单号"
            style={{ width: 200 }}
            defaultValue={soNo}
            onSearch={(v) => {
              setSoNo(v.trim());
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
          {sourceSalesOrderId && (
            <Button size="small" onClick={() => router.push("/purchasing/orders")}>
              清除来源销售单筛选
            </Button>
          )}
        </Space>
        <Can perm={Permissions.PURCHASE_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
            新建采购单
          </Button>
        </Can>
      </Space>

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<PurchaseOrderListItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 1200 }}
            locale={{ emptyText: "暂无采购单" }}
            onRow={(r) => ({
              onClick: () => router.push(`/purchasing/orders/${r.id}`),
              style: { cursor: "pointer" },
            })}
            pagination={pagination}
          />
        )}
      </ListPageBody>

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
    </ListPageCard>
  );
}
