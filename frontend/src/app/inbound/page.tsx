"use client";
import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Empty, Input, Segmented, Space } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { StatusTag } from "@/components/common/StatusTag";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { Permissions } from "@/config/permission-matrix";
import { formatDateTime, formatQty } from "@/lib/format";
import { inboundOrderApi, type InboundOrderListItem } from "@/lib/inboundOrder";
import { INBOUND_ORDER_STATUS_META } from "@/lib/inboundOrderStatus";
import { InboundOrderBuilder } from "@/components/inbound/InboundOrderBuilder";
import { PurchaseOrderPicker } from "@/components/inbound/PurchaseOrderPicker";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "在途", value: "IN_TRANSIT" },
  { label: "已入库", value: "RECEIVED" },
  { label: "已作废", value: "CANCELLED" },
];

export default function InboundOrderListPage() {
  const router = useRouter();

  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  // 建单 pull 入口:先选一张 CONFIRMED PO(picker),选定后带 PO id 打开建单器。
  const [pickerOpen, setPickerOpen] = useState(false);
  const [builderSourceId, setBuilderSourceId] = useState<number | null>(null);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      inboundOrderApi.list({
        status: status || undefined,
        keyword: keyword || undefined,
        page,
        size,
      }),
    [status, keyword],
  );
  const { rows, setPage, loading, loadError, load, pagination } =
    useListQuery<InboundOrderListItem>(fetcher, { errorMessage: "加载入库单列表失败" });

  // 入库单据零成本列(契约 D3):列表无任何金额/成本列。
  const columns: ColumnsType<InboundOrderListItem> = [
    { title: "入库单号", dataIndex: "no", width: 160 },
    {
      // 上游单据:有 purchase:read 即可点击跳采购单详情,无权限降级纯文本(DESIGN §7)。
      // 行本身点击进入库详情,故 PO 链接需 stopPropagation 阻止冒泡。
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
    { title: "供应商", dataIndex: "supplier_display", width: 170, ellipsis: true },
    {
      title: "承运商 / 头程单号",
      key: "carrier",
      width: 200,
      render: (_, r) => {
        const parts = [r.carrier_name, r.tracking_no].filter(Boolean);
        return parts.length ? parts.join(" · ") : "—";
      },
    },
    {
      title: "预计到货",
      dataIndex: "eta",
      width: 120,
      render: (v: string | null) => v || "—",
    },
    {
      title: "行数 / 总数量",
      key: "qty",
      width: 120,
      align: "right",
      render: (_, r) => `${r.line_count} / ${formatQty(r.total_qty)}`,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      render: (s: InboundOrderListItem["status"]) => (
        <StatusTag meta={INBOUND_ORDER_STATUS_META} value={s} />
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
      {/* 工具条统一次序(DESIGN §7):状态 → 搜索;标题由面包屑承担,不重复。 */}
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
            placeholder="入库单号 / 头程单号 / 采购单号"
            style={{ width: 280 }}
            defaultValue={keyword}
            onSearch={(v) => {
              setKeyword(v.trim());
              setPage(1);
            }}
          />
        </Space>
        <Can perm={Permissions.INBOUND_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
            登记入库
          </Button>
        </Can>
      </Space>

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<InboundOrderListItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 1180 }}
            locale={{
              emptyText: (
                <Empty description="暂无入库单">
                  <Can perm={Permissions.INBOUND_MANAGE}>
                    <Button type="primary" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
                      登记入库
                    </Button>
                  </Can>
                </Empty>
              ),
            }}
            onRow={(r) => ({
              onClick: () => router.push(`/inbound/${r.id}`),
              style: { cursor: "pointer" },
            })}
            pagination={pagination}
          />
        )}
      </ListPageBody>

      {/* pull 入口:选 CONFIRMED PO → 打开建单器。入库单恒绑单一 PO,故先选一张。 */}
      <PurchaseOrderPicker
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPick={(poId) => {
          setPickerOpen(false);
          setBuilderSourceId(poId);
        }}
      />
      <InboundOrderBuilder
        open={builderSourceId !== null}
        mode="create"
        purchaseOrderId={builderSourceId ?? 0}
        onClose={() => setBuilderSourceId(null)}
        onSaved={() => {
          setBuilderSourceId(null);
          load();
        }}
      />
    </ListPageCard>
  );
}
