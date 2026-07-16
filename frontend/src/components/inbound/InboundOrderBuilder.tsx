"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Checkbox,
  Col,
  DatePicker,
  Drawer,
  Form,
  Input,
  InputNumber,
  Row,
  Space,
  Spin,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";
import { colors } from "@/lib/tokens";
import { formatQty } from "@/lib/salesOrder";
import {
  inboundErrorMessage,
  inboundOrderApi,
  type InboundOrderLineIn,
} from "@/lib/inboundOrder";

// 🔴 入库单据无任何成本字段(契约 D3):建单器只录数量 + 头程物流,不含采购价/金额。

/** 建单器编辑行:候选可收行 ∪ 既有入库行(编辑态)。 */
interface BuilderRow {
  purchase_order_line_id: number;
  existing?: boolean; // 编辑态既有入库行(客户端跳过超收拦截,以后端为准)
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  ordered_qty?: number;
  in_transit_qty?: number;
  received_qty?: number;
  remaining_qty?: number; // 来自可收行;既有行未出现在可收集时为 undefined
  selected: boolean;
  qty: number;
}

export function InboundOrderBuilder({
  open,
  mode,
  purchaseOrderId,
  orderId,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  purchaseOrderId: number;
  orderId?: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();

  const [rows, setRows] = useState<BuilderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const purRes = await inboundOrderApi.receivableLines(purchaseOrderId);

      // 候选行(可收集):默认未选,数量预填剩余可收量。
      const byLine = new Map<number, BuilderRow>();
      purRes.items.forEach((p) => {
        byLine.set(p.purchase_order_line_id, {
          purchase_order_line_id: p.purchase_order_line_id,
          name_snapshot: p.name_snapshot,
          spec_text_snapshot: p.spec_text_snapshot,
          unit_snapshot: p.unit_snapshot,
          ordered_qty: Number(p.ordered_qty),
          in_transit_qty: Number(p.in_transit_qty),
          received_qty: Number(p.received_qty),
          remaining_qty: Number(p.remaining_qty),
          selected: false,
          qty: Number(p.remaining_qty),
        });
      });

      if (mode === "edit" && orderId) {
        const { order, lines } = await inboundOrderApi.get(orderId);
        form.setFieldsValue({
          carrier_name: order.carrier_name ?? undefined,
          tracking_no: order.tracking_no ?? undefined,
          shipped_at: order.shipped_at ? dayjs(order.shipped_at) : undefined,
          eta: order.eta ? dayjs(order.eta) : undefined,
          remark: order.remark ?? undefined,
        });
        // 既有入库行覆盖候选行(勾选+回填);源行不在可收集时补一条(remaining 未知)。
        lines.forEach((l) => {
          const existing = byLine.get(l.purchase_order_line_id);
          const merged: BuilderRow = {
            purchase_order_line_id: l.purchase_order_line_id,
            existing: true,
            name_snapshot: l.name_snapshot,
            spec_text_snapshot: l.spec_text_snapshot,
            unit_snapshot: l.unit_snapshot,
            ordered_qty: existing?.ordered_qty,
            in_transit_qty: existing?.in_transit_qty,
            received_qty: existing?.received_qty,
            remaining_qty: existing?.remaining_qty,
            selected: true,
            qty: Number(l.qty),
          };
          byLine.set(l.purchase_order_line_id, merged);
        });
      } else {
        // 建单态:清空头程物流字段,避免复用同一实例连选多张 PO 时残留上次输入。
        form.resetFields();
      }
      setRows(Array.from(byLine.values()));
    } catch (e) {
      message.error(inboundErrorMessage(e, "加载可收行失败"));
      onClose();
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, orderId, purchaseOrderId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const patchRow = (lid: number, patch: Partial<BuilderRow>) =>
    setRows((rs) => rs.map((r) => (r.purchase_order_line_id === lid ? { ...r, ...patch } : r)));

  const selectedRows = useMemo(() => rows.filter((r) => r.selected), [rows]);
  const totalQty = useMemo(
    () => selectedRows.reduce((s, r) => s + (r.qty || 0), 0),
    [selectedRows],
  );

  async function onSubmit() {
    let header: {
      carrier_name?: string;
      tracking_no?: string;
      shipped_at?: dayjs.Dayjs;
      eta?: dayjs.Dayjs;
      remark?: string;
    };
    try {
      header = await form.validateFields();
    } catch {
      return;
    }
    if (selectedRows.length === 0) {
      message.error("至少勾选一行");
      return;
    }
    // 逐行校验:数量>0;新增行(非既有)客户端拦超收(数量≤剩余可收量)。
    for (const r of selectedRows) {
      if (!r.qty || r.qty <= 0) {
        message.error(`「${r.name_snapshot}」数量需大于 0`);
        return;
      }
      if (!r.existing && r.remaining_qty !== undefined && r.qty > r.remaining_qty) {
        message.error(`「${r.name_snapshot}」数量超过剩余可收量 ${formatQty(r.remaining_qty)}`);
        return;
      }
    }

    const lines: InboundOrderLineIn[] = selectedRows.map((r, i) => ({
      purchase_order_line_id: r.purchase_order_line_id,
      qty: r.qty,
      sort_order: i,
    }));

    const payload = {
      carrier_name: header.carrier_name?.trim() || null,
      tracking_no: header.tracking_no?.trim() || null,
      shipped_at: header.shipped_at ? header.shipped_at.format("YYYY-MM-DD") : null,
      eta: header.eta ? header.eta.format("YYYY-MM-DD") : null,
      remark: header.remark?.trim() || null,
      lines,
    };

    setSaving(true);
    try {
      if (mode === "create") {
        const { order } = await inboundOrderApi.create({
          purchase_order_id: purchaseOrderId,
          ...payload,
        });
        message.success(`已生成入库单 ${order.no}`);
      } else if (orderId) {
        await inboundOrderApi.update(orderId, payload);
        message.success("已保存");
      }
      onSaved();
    } catch (e) {
      message.error(inboundErrorMessage(e, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  const numCell = (v?: number) =>
    v === undefined ? <span style={{ color: colors.muted }}>—</span> : formatQty(v);

  const columns: ColumnsType<BuilderRow> = [
    {
      title: "",
      key: "sel",
      width: 40,
      render: (_, r) => (
        <Checkbox
          checked={r.selected}
          onChange={(e) => patchRow(r.purchase_order_line_id, { selected: e.target.checked })}
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
    { title: "单位", dataIndex: "unit_snapshot", width: 64 },
    { title: "已订", key: "ordered", width: 72, align: "right", render: (_, r) => numCell(r.ordered_qty) },
    { title: "在途", key: "intransit", width: 72, align: "right", render: (_, r) => numCell(r.in_transit_qty) },
    { title: "已入", key: "received", width: 72, align: "right", render: (_, r) => numCell(r.received_qty) },
    { title: "剩余", key: "remaining", width: 72, align: "right", render: (_, r) => numCell(r.remaining_qty) },
    {
      title: "本次数量",
      key: "qty",
      width: 120,
      render: (_, r) => (
        <InputNumber
          min={0.001}
          value={r.qty}
          onChange={(v) =>
            // 一动数量即自动勾选该行(免去先找左侧复选框);取消勾选仍走复选框。
            patchRow(r.purchase_order_line_id, { qty: Number(v) || 0, selected: true })
          }
          style={{ width: "100%" }}
        />
      ),
    },
  ];

  return (
    <Drawer
      title={mode === "create" ? "登记入库" : "编辑入库单"}
      open={open}
      onClose={onClose}
      width="min(920px, 96vw)"
      destroyOnClose
      footer={
        <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
          <span style={{ fontWeight: 600, color: colors.navy }}>
            已选 {selectedRows.length} 行 · 合计数量 {formatQty(totalQty)}
          </span>
          <Space>
            <Button onClick={onClose} disabled={saving}>
              取消
            </Button>
            <Button type="primary" loading={saving} onClick={onSubmit}>
              {mode === "create" ? "生成入库单" : "保存"}
            </Button>
          </Space>
        </Space>
      }
    >
      {loading ? (
        <Spin style={{ display: "block", marginTop: 80 }} />
      ) : (
        <>
          <div style={{ maxWidth: 760 }}>
            <Form form={form} layout="vertical">
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item name="carrier_name" label="承运商">
                    <Input placeholder="选填,如 头程货代 / 船公司" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="tracking_no" label="头程单号">
                    <Input placeholder="选填,如 提单号 / 运单号" />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="shipped_at" label="发货日期">
                    <DatePicker style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item name="eta" label="预计到货">
                    <DatePicker style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
              </Row>
              <Form.Item name="remark" label="备注" style={{ marginBottom: 12 }}>
                <Input.TextArea rows={2} placeholder="选填" />
              </Form.Item>
            </Form>
          </div>

          <div style={{ marginBottom: 8, color: colors.muted, fontSize: 12 }}>
            勾选可收行、录本次入库数量。可分批入库(受剩余可收量约束);同一采购单可多次登记入库。
          </div>
          <Table<BuilderRow>
            rowKey="purchase_order_line_id"
            size="small"
            columns={columns}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 820 }}
            locale={{ emptyText: "该采购单已无可收行" }}
          />
        </>
      )}
    </Drawer>
  );
}
