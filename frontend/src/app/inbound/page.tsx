"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { App, Button, Card, Empty, Input, Segmented, Space, Table, Tag } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { formatQty } from "@/lib/salesOrder";
import { inboundOrderApi, type InboundOrderListItem } from "@/lib/inboundOrder";
import { INBOUND_ORDER_STATUS_META } from "@/lib/inboundOrderStatus";
import { InboundOrderBuilder } from "@/components/inbound/InboundOrderBuilder";
import { PurchaseOrderPicker } from "@/components/inbound/PurchaseOrderPicker";
import { colors } from "@/lib/tokens";

const STATUS_TABS = [
  { label: "全部", value: "" },
  { label: "在途", value: "IN_TRANSIT" },
  { label: "已入库", value: "RECEIVED" },
  { label: "已作废", value: "CANCELLED" },
];

export default function InboundOrderListPage() {
  const router = useRouter();
  const { message } = App.useApp();

  const [rows, setRows] = useState<InboundOrderListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  // 建单 pull 入口:先选一张 CONFIRMED PO(picker),选定后带 PO id 打开建单器。
  const [pickerOpen, setPickerOpen] = useState(false);
  const [builderSourceId, setBuilderSourceId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await inboundOrderApi.list({
        status: status || undefined,
        keyword: keyword || undefined,
        page,
        size: 20,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      setLoadError(true);
      message.error(e instanceof Error ? e.message : "加载入库单列表失败");
    } finally {
      setLoading(false);
    }
  }, [status, keyword, page, message]);

  useEffect(() => {
    load();
  }, [load]);

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
      render: (s: InboundOrderListItem["status"]) => {
        const m = INBOUND_ORDER_STATUS_META[s];
        return <Tag color={m.color}>{m.label}</Tag>;
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
      title="入库单"
      extra={
        <Can perm={Permissions.INBOUND_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
            登记入库
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

      {loadError && !rows.length ? (
        <div style={{ textAlign: "center", padding: "48px 0", color: colors.muted }}>
          加载失败
          <div style={{ marginTop: 12 }}>
            <Button onClick={load}>重试</Button>
          </div>
        </div>
      ) : (
        <Table<InboundOrderListItem>
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
    </Card>
  );
}
