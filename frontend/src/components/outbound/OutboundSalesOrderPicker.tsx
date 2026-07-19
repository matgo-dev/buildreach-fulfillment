"use client";
import { useCallback, useState } from "react";
import { App, Input, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { PickerDrawer } from "@/components/common/PickerDrawer";
import { salesOrderApi, type SalesOrderListItem } from "@/lib/salesOrder";

/**
 * 组柜工作台「添加出库单」入口:选一张 CONFIRMED 销售单作为出库来源,选定后由父级打开建单器。
 * 🔴 不展示任何售价/金额(出库/柜链路红线):只列 销售单号 + 客户,足够识别。
 * 前端预拦:同柜该 SO 已有活动出库单(activeSoIds)→ 标记「已在本柜」并拦截选择(后端 41904 兜底)。
 * 「有可发」由建单器加载可发行后兜底(无可发行时提示),此处不额外过滤。
 */
export function OutboundSalesOrderPicker({
  open,
  onClose,
  onPick,
  activeSoIds,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (salesOrderId: number) => void;
  /** 本柜已存在活动出库单的来源 SO id 集合(前端预拦)。 */
  activeSoIds: number[];
}) {
  const { message } = App.useApp();
  const [soNo, setSoNo] = useState("");

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      salesOrderApi.list({ status: "CONFIRMED", no: soNo || undefined, page, size }),
    [soNo],
  );

  const columns: ColumnsType<SalesOrderListItem> = [
    { title: "销售单号", dataIndex: "no", width: 160 },
    { title: "客户", dataIndex: "customer_display", width: 180, ellipsis: true },
    {
      title: "",
      key: "hint",
      width: 96,
      render: (_, r) =>
        activeSoIds.includes(r.id) ? <Tag color="default">已在本柜</Tag> : null,
    },
  ];

  return (
    <PickerDrawer<SalesOrderListItem>
      title="选择销售单添加出库单"
      open={open}
      onClose={onClose}
      onPick={(r) => {
        // 同柜同 SO 已有活动出库单 → 前端预拦(后端偏唯一 41904 兜底)。
        if (activeSoIds.includes(r.id)) {
          message.warning("该柜内此销售单已有活动出库单,不可重复添加");
          return;
        }
        onPick(r.id);
      }}
      columns={columns}
      fetcher={fetcher}
      toolbar={({ resetPage }) => (
        <Input.Search
          allowClear
          placeholder="销售单号"
          style={{ width: 240 }}
          defaultValue={soNo}
          onSearch={(v) => {
            setSoNo(v.trim());
            resetPage();
          }}
        />
      )}
      errorMessage="加载销售单失败"
      emptyText="暂无已确认销售单"
      scrollX={460}
    />
  );
}
