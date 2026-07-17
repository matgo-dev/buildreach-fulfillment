"use client";
import { useCallback, useState } from "react";
import { Input, Segmented } from "antd";
import type { ColumnsType } from "antd/es/table";
import { PickerDrawer } from "@/components/common/PickerDrawer";
import { StatusTag } from "@/components/common/StatusTag";
import { formatMoney } from "@/lib/format";
import { salesOrderApi, type SalesOrderListItem } from "@/lib/salesOrder";
import { PURCHASE_PROGRESS_META } from "@/lib/purchaseOrderStatus";

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
  const [progress, setProgress] = useState("");
  const [soNo, setSoNo] = useState("");

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      salesOrderApi.list({
        status: "CONFIRMED",
        no: soNo || undefined,
        purchase_progress: progress || undefined,
        purchasable_only: true, // 只列可发起采购的 SO(已采完的排除,不在此展示)
        page,
        size,
      }),
    [progress, soNo],
  );

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
      render: (p: SalesOrderListItem["purchase_progress"]) =>
        p ? <StatusTag meta={PURCHASE_PROGRESS_META} value={p} /> : "—",
    },
  ];

  return (
    <PickerDrawer<SalesOrderListItem>
      title="选择销售单发起采购"
      open={open}
      onClose={onClose}
      onPick={(r) => onPick(r.id)}
      columns={columns}
      fetcher={fetcher}
      toolbar={({ resetPage }) => (
        <>
          <Segmented
            options={PROGRESS_TABS}
            value={progress}
            onChange={(v) => {
              setProgress(v as string);
              resetPage();
            }}
          />
          <Input.Search
            allowClear
            placeholder="销售单号"
            style={{ width: 200 }}
            defaultValue={soNo}
            onSearch={(v) => {
              setSoNo(v.trim());
              resetPage();
            }}
          />
        </>
      )}
      errorMessage="加载销售单失败"
      emptyText="暂无可发起采购的销售单"
      scrollX={640}
    />
  );
}
