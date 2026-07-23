"use client";
import { useCallback, useEffect, useState } from "react";
import { Input, Select, Space } from "antd";
import type { ColumnsType } from "antd/es/table";
import { PickerDrawer } from "@/components/common/PickerDrawer";
import { ProgressCell } from "@/components/common/ProgressCell";
import { purchaseOrderApi, type PurchaseOrderListItem } from "@/lib/purchaseOrder";
import { RECEIPT_PROGRESS_META } from "@/lib/inboundOrderStatus";
import { InTransitBadge } from "@/components/inbound/InTransitBadge";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";

/**
 * 入库台 pull 入口:选一张 CONFIRMED 采购单作为入库来源,选定后由父级打开建单器。
 * 入库单恒绑单一 PO —— 此处只选一张;已全部入库(FULLY_RECEIVED)的 PO 仍可见(标徽标),
 * 但打开建单器后若已无可收行会提示。收货进度徽标帮运营快速判断哪些还需收货。
 */
export function PurchaseOrderPicker({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (purchaseOrderId: number) => void;
}) {
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined);
  const [soNo, setSoNo] = useState("");
  const [suppliers, setSuppliers] = useState<SupplierListItem[]>([]);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      purchaseOrderApi.list({
        status: "CONFIRMED",
        supplier_id: supplierId,
        source_sales_order_no: soNo || undefined,
        page,
        size,
      }),
    [supplierId, soNo],
  );

  // 供应商筛选下拉(启用+停用都要,便于筛历史)。
  useEffect(() => {
    supplierApi
      .list({ size: 100 })
      .then((res) => setSuppliers(res.items))
      .catch(() => undefined);
  }, []);

  const columns: ColumnsType<PurchaseOrderListItem> = [
    { title: "采购单号", dataIndex: "no", width: 160 },
    { title: "供应商", dataIndex: "supplier_display", width: 170, ellipsis: true },
    {
      title: "收货进度",
      dataIndex: "receipt_progress",
      width: 150,
      // 选单时并列在途信号:直接告诉运营「这张已有几张在途单」,避免重复登记。
      render: (p: PurchaseOrderListItem["receipt_progress"], r) => (
        <Space size={4}>
          {p ? <ProgressCell meta={RECEIPT_PROGRESS_META} value={p} /> : <span>—</span>}
          <InTransitBadge count={r.in_transit_count} />
        </Space>
      ),
    },
  ];

  return (
    <PickerDrawer<PurchaseOrderListItem>
      title="选择采购单登记入库"
      open={open}
      onClose={onClose}
      onPick={(r) => onPick(r.id)}
      columns={columns}
      fetcher={fetcher}
      toolbar={({ resetPage }) => (
        <>
          <Select
            allowClear
            showSearch
            placeholder="供应商"
            optionFilterProp="label"
            style={{ width: 220 }}
            value={supplierId}
            onChange={(v) => {
              setSupplierId(v);
              resetPage();
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
              resetPage();
            }}
          />
        </>
      )}
      errorMessage="加载采购单失败"
      emptyText="暂无已确认采购单"
      scrollX={620}
    />
  );
}
