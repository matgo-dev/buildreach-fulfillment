"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Checkbox,
  Col,
  Drawer,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Spin,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { colors } from "@/lib/tokens";
import { formatMoney, formatQty } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import { supplierApi, type SupplierListItem } from "@/lib/supplier";
import {
  purchaseOrderApi,
  type PurchaseOrderLineIn,
} from "@/lib/purchaseOrder";

// 币种可选值(ISO4217,与供应商/销售口径一致)。
import { CURRENCY_OPTIONS } from "@/lib/currencies";

/** 建单器编辑行:候选可采行 ∪ 既有采购行(编辑态)。 */
interface BuilderRow {
  source_sales_order_line_id: number;
  poLineId?: number; // 既有采购行 id(编辑态回填);无=新增行
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  remaining_qty?: number; // 来自可采行;既有行未出现在可采集时为 undefined(不客户端拦额度)
  selected: boolean;
  qty: number;
  unit_price: number | null;
}

export function PurchaseOrderBuilder({
  open,
  mode,
  sourceSalesOrderId,
  orderId,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  sourceSalesOrderId: number;
  orderId?: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();

  const [suppliers, setSuppliers] = useState<SupplierListItem[]>([]);
  const [rows, setRows] = useState<BuilderRow[]>([]);
  const [expectedUpdatedAt, setExpectedUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [supRes, purRes] = await Promise.all([
        supplierApi.list({ status: "ACTIVE", size: 100 }),
        purchaseOrderApi.purchasableLines(sourceSalesOrderId),
      ]);
      setSuppliers(supRes.items);

      // 候选行(可采集):默认未选,数量预填剩余额度,采购价预填建议价。
      const byLine = new Map<number, BuilderRow>();
      purRes.items.forEach((p) => {
        byLine.set(p.source_sales_order_line_id, {
          source_sales_order_line_id: p.source_sales_order_line_id,
          name_snapshot: p.name_snapshot,
          spec_text_snapshot: p.spec_text_snapshot,
          unit_snapshot: p.unit_snapshot,
          remaining_qty: Number(p.remaining_qty),
          selected: false,
          qty: Number(p.remaining_qty),
          unit_price: p.default_unit_price === null ? null : Number(p.default_unit_price),
        });
      });

      if (mode === "edit" && orderId) {
        const { order, lines } = await purchaseOrderApi.get(orderId);
        setExpectedUpdatedAt(order.updated_at);
        form.setFieldsValue({
          supplier_id: order.supplier_id,
          currency: order.currency,
          remark: order.remark ?? undefined,
        });
        // 既有采购行覆盖候选行(勾选+回填);源行不在可采集时补一条(remaining 未知)。
        lines.forEach((l) => {
          const existing = byLine.get(l.source_sales_order_line_id);
          const merged: BuilderRow = {
            source_sales_order_line_id: l.source_sales_order_line_id,
            poLineId: l.id,
            name_snapshot: l.name_snapshot,
            spec_text_snapshot: l.spec_text_snapshot,
            unit_snapshot: l.unit_snapshot,
            remaining_qty: existing?.remaining_qty,
            selected: true,
            qty: Number(l.qty),
            unit_price: l.unit_price === null ? null : Number(l.unit_price),
          };
          byLine.set(l.source_sales_order_line_id, merged);
        });
      } else {
        // 建单态:清空表头(供应商/币种/备注),避免复用同一实例连选多张 SO 时残留上次输入。
        form.resetFields();
      }
      setRows(Array.from(byLine.values()));
    } catch (e) {
      message.error(resolveBizError(e, "加载可采行失败"));
      onClose();
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, orderId, sourceSalesOrderId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const patchRow = (sid: number, patch: Partial<BuilderRow>) =>
    setRows((rs) => rs.map((r) => (r.source_sales_order_line_id === sid ? { ...r, ...patch } : r)));

  // 选供应商时,若币种未填则带出供应商默认币种(便利,非强制)。
  function onSupplierChange(id: number) {
    const sup = suppliers.find((s) => s.id === id);
    if (sup?.default_currency && !form.getFieldValue("currency")) {
      form.setFieldValue("currency", sup.default_currency);
    }
  }

  const selectedRows = useMemo(() => rows.filter((r) => r.selected), [rows]);
  const total = useMemo(
    () => selectedRows.reduce((s, r) => s + (r.unit_price || 0) * (r.qty || 0), 0),
    [selectedRows],
  );

  async function onSubmit() {
    let header: { supplier_id: number; currency: string; remark?: string };
    try {
      header = await form.validateFields();
    } catch {
      return;
    }
    if (selectedRows.length === 0) {
      message.error("至少勾选一行");
      return;
    }
    // 逐行校验:数量>0、采购价必填;新增行(无 poLineId)客户端拦超采(数量≤剩余额度)。
    for (const r of selectedRows) {
      if (!r.qty || r.qty <= 0) {
        message.error(`「${r.name_snapshot}」数量需大于 0`);
        return;
      }
      if (r.unit_price === null || r.unit_price < 0) {
        message.error(`「${r.name_snapshot}」需录入采购价`);
        return;
      }
      if (!r.poLineId && r.remaining_qty !== undefined && r.qty > r.remaining_qty) {
        message.error(`「${r.name_snapshot}」数量超过剩余额度 ${formatQty(r.remaining_qty)}`);
        return;
      }
    }

    const lines: PurchaseOrderLineIn[] = selectedRows.map((r, i) => ({
      id: r.poLineId,
      source_sales_order_line_id: r.source_sales_order_line_id,
      qty: r.qty,
      unit_price: r.unit_price as number,
      sort_order: i,
    }));

    setSaving(true);
    try {
      if (mode === "create") {
        const { order } = await purchaseOrderApi.create({
          source_sales_order_id: sourceSalesOrderId,
          supplier_id: header.supplier_id,
          currency: header.currency,
          remark: header.remark ?? null,
          lines,
        });
        message.success(`已生成采购单 ${order.no}`);
      } else if (orderId) {
        await purchaseOrderApi.update(orderId, {
          supplier_id: header.supplier_id,
          currency: header.currency,
          remark: header.remark ?? null,
          lines,
          expected_updated_at: expectedUpdatedAt as string,
        });
        message.success("已保存");
      }
      onSaved();
    } catch (e) {
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  const columns: ColumnsType<BuilderRow> = [
    {
      title: "",
      key: "sel",
      width: 40,
      render: (_, r) => (
        <Checkbox
          checked={r.selected}
          onChange={(e) => patchRow(r.source_sales_order_line_id, { selected: e.target.checked })}
        />
      ),
    },
    { title: "商品", dataIndex: "name_snapshot", ellipsis: true },
    {
      title: "规格",
      dataIndex: "spec_text_snapshot",
      ellipsis: true,
      render: (v) => v || <span style={{ color: colors.muted }}>—</span>,
    },
    { title: "单位", dataIndex: "unit_snapshot", width: 70 },
    {
      title: "剩余额度",
      key: "remaining",
      width: 90,
      align: "right",
      render: (_, r) =>
        r.remaining_qty === undefined ? (
          <span style={{ color: colors.muted }}>—</span>
        ) : (
          formatQty(r.remaining_qty)
        ),
    },
    {
      title: "采购数量",
      key: "qty",
      width: 120,
      render: (_, r) => (
        <InputNumber
          min={0.001}
          value={r.qty}
          onChange={(v) =>
            // 一动数量即自动勾选该行(免去先找左侧复选框);取消勾选仍走复选框。
            patchRow(r.source_sales_order_line_id, { qty: Number(v) || 0, selected: true })
          }
          style={{ width: "100%" }}
        />
      ),
    },
    {
      title: "采购价",
      key: "unit_price",
      width: 130,
      render: (_, r) => (
        <InputNumber
          min={0}
          value={r.unit_price ?? undefined}
          placeholder="必填"
          onChange={(v) =>
            patchRow(r.source_sales_order_line_id, {
              unit_price: v === null ? null : Number(v),
              selected: true,
            })
          }
          style={{ width: "100%" }}
        />
      ),
    },
  ];

  return (
    <Drawer
      title={mode === "create" ? "发起采购" : "编辑采购单"}
      open={open}
      onClose={onClose}
      width="min(900px, 96vw)"
      destroyOnClose
      footer={
        <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
          <span style={{ fontWeight: 600, color: colors.navy }}>
            已选 {selectedRows.length} 行 · 合计 {formatMoney(total)}
          </span>
          <Space>
            <Button onClick={onClose} disabled={saving}>
              取消
            </Button>
            <Button type="primary" loading={saving} onClick={onSubmit}>
              {mode === "create" ? "生成采购单" : "保存"}
            </Button>
          </Space>
        </Space>
      }
    >
      {loading ? (
        <Spin style={{ display: "block", marginTop: 80 }} />
      ) : (
        <>
          <div style={{ maxWidth: 720 }}>
            <Form form={form} layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item
                    name="supplier_id"
                    label="供应商"
                    rules={[{ required: true, message: "选择供应商" }]}
                  >
                    <Select
                      showSearch
                      placeholder="选择供应商(仅启用)"
                      optionFilterProp="label"
                      onChange={onSupplierChange}
                      options={suppliers.map((s) => ({ value: s.id, label: `${s.code} · ${s.name}` }))}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="currency" label="币种" rules={[{ required: true, message: "选择币种" }]}>
                    <Select options={CURRENCY_OPTIONS} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="remark" label="备注" style={{ marginBottom: 12 }}>
                <Input.TextArea rows={2} placeholder="选填" />
              </Form.Item>
            </Form>
          </div>

          <div style={{ marginBottom: 8, color: colors.muted, fontSize: 12 }}>
            勾选可采行、录采购数量与采购价。每次提交生成一张采购单(单一供应商);多供应商或同一供应商分批采购,分次提交即可(受剩余额度约束)。
          </div>
          <Table<BuilderRow>
            rowKey="source_sales_order_line_id"
            size="small"
            columns={columns}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 760 }}
            locale={{ emptyText: "该销售单已无可采行" }}
          />
        </>
      )}
    </Drawer>
  );
}
