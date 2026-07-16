"use client";
import { useCallback, useEffect, useState } from "react";
import { App, Button, Drawer, Input, Select, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";
import { purchaseOrderApi, type PurchaseOrderListItem } from "@/lib/purchaseOrder";
import { RECEIPT_PROGRESS_META } from "@/lib/inboundOrderStatus";
import { InTransitBadge } from "@/components/inbound/InTransitBadge";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";
import { colors } from "@/lib/tokens";

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
  const { message } = App.useApp();
  const [rows, setRows] = useState<PurchaseOrderListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [supplierId, setSupplierId] = useState<number | undefined>(undefined);
  const [soNo, setSoNo] = useState("");
  const [suppliers, setSuppliers] = useState<SupplierListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await purchaseOrderApi.list({
        status: "CONFIRMED",
        supplier_id: supplierId,
        source_sales_order_no: soNo || undefined,
        page,
        size: 10,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      setLoadError(true);
      message.error(e instanceof Error ? e.message : "加载采购单失败");
    } finally {
      setLoading(false);
    }
  }, [supplierId, soNo, page, message]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

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
      render: (p: PurchaseOrderListItem["receipt_progress"], r) => {
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
      title: "",
      key: "action",
      width: 72,
      fixed: "right",
      render: (_: unknown, r) => (
        <Button type="link" size="small" onClick={() => onPick(r.id)}>
          选择
        </Button>
      ),
    },
  ];

  return (
    <Drawer title="选择采购单登记入库" width={720} open={open} onClose={onClose} destroyOnClose>
      <Space style={{ marginBottom: 16 }} wrap>
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
          size="small"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 620 }}
          locale={{ emptyText: "暂无已确认采购单" }}
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
