"use client";
import { useCallback, useEffect, useState } from "react";
import { App, Button, Drawer, Segmented, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { formatMoney, salesOrderApi, type SalesOrderListItem } from "@/lib/salesOrder";
import { PURCHASE_PROGRESS_META } from "@/lib/purchaseOrderStatus";
import { colors } from "@/lib/tokens";

// 采购进度筛选(采购台常问「哪些 SO 还没下齐」)。复用 GET /sales-orders?purchase_progress=。
const PROGRESS_TABS = [
  { label: "全部", value: "" },
  { label: "未下单", value: "NOT_ORDERED" },
  { label: "部分下单", value: "PARTIALLY_ORDERED" },
];

/**
 * 采购台 pull 入口:选一张 CONFIRMED 销售单作为采购来源,选定后由父级打开建单器。
 * 采购单恒绑单一 SO —— 此处只选一张;已采完(FULLY_ORDERED)不可再发起(置灰)。
 */
export function SalesOrderPicker({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (salesOrderId: number) => void;
}) {
  const { message } = App.useApp();
  const [rows, setRows] = useState<SalesOrderListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [progress, setProgress] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await salesOrderApi.list({
        status: "CONFIRMED",
        purchase_progress: progress || undefined,
        page,
        size: 10,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      setLoadError(true);
      message.error(e instanceof Error ? e.message : "加载销售单失败");
    } finally {
      setLoading(false);
    }
  }, [progress, page, message]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const columns: ColumnsType<SalesOrderListItem> = [
    { title: "销售单号", dataIndex: "no", width: 150 },
    { title: "客户", dataIndex: "customer_display", width: 160, ellipsis: true },
    {
      title: "金额",
      dataIndex: "total_amount",
      width: 130,
      align: "right",
      render: (v: number | string, r) => `${r.currency} ${formatMoney(v)}`,
    },
    {
      title: "采购进度",
      dataIndex: "purchase_progress",
      width: 110,
      render: (p: SalesOrderListItem["purchase_progress"]) => {
        if (!p) return "—";
        const m = PURCHASE_PROGRESS_META[p];
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    {
      title: "",
      key: "action",
      width: 88,
      fixed: "right",
      render: (_: unknown, r) => {
        const done = r.purchase_progress === "FULLY_ORDERED";
        return (
          <Button type="link" size="small" disabled={done} onClick={() => onPick(r.id)}>
            {done ? "已采完" : "选择"}
          </Button>
        );
      },
    },
  ];

  return (
    <Drawer title="选择销售单发起采购" width={720} open={open} onClose={onClose} destroyOnClose>
      <Space style={{ marginBottom: 16 }}>
        <Segmented
          options={PROGRESS_TABS}
          value={progress}
          onChange={(v) => {
            setProgress(v as string);
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
        <Table<SalesOrderListItem>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 640 }}
          locale={{ emptyText: "暂无可发起采购的销售单" }}
          pagination={{
            current: page,
            total,
            pageSize: 10,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: setPage,
          }}
        />
      )}
    </Drawer>
  );
}
