"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Checkbox,
  Drawer,
  Form,
  Input,
  InputNumber,
  Space,
  Spin,
  Table,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { colors } from "@/lib/tokens";
import { formatQty } from "@/lib/format";
import { NumCell } from "@/components/common/NumCell";
import { resolveBizError } from "@/lib/errorMessages";
import { outboundOrderApi, type OutboundOrderLineIn } from "@/lib/outboundOrder";

// 🔴 出库单据无任何售价/成本字段(契约 §3):建单器只挑 SO 行 + 录出库数量,不含金额。

/** 建单器编辑行:候选可发行 ∪ 既有出库行(编辑态)。 */
interface BuilderRow {
  sales_order_line_id: number;
  existing?: boolean; // 编辑态既有出库行
  name_snapshot: string;
  spec_text_snapshot: string;
  unit_snapshot: string;
  ordered_qty?: number;
  outbound_qty?: number;
  available_qty?: number; // 来自可发行;既有行未出现在可发集时为 undefined
  selected: boolean;
  qty: number;
}

export function OutboundOrderBuilder({
  open,
  mode,
  shipmentId,
  salesOrderId,
  orderId,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  /** 建单态:目标柜(锚定,后端偏唯一保「一柜内每来源 SO 各一张」)。 */
  shipmentId?: number;
  /** 来源销售单(建单态父级传;编辑态可省,加载后以订单为准)。 */
  salesOrderId: number;
  orderId?: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();

  const [rows, setRows] = useState<BuilderRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  // 乐观锁基线 = 打开编辑时的 updated_at;保存时随 payload 上送,后端不一致 → 409(对齐 PO/入库)。
  const [expectedUpdatedAt, setExpectedUpdatedAt] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // 编辑态先取订单(拿 sales_order_id / 既有行 / 乐观锁基线),再取该 SO 可发行。
      let soId = salesOrderId;
      let existingLines: { sales_order_line_id: number; name_snapshot: string; spec_text_snapshot: string; unit_snapshot: string; qty: number | string }[] = [];
      if (mode === "edit" && orderId) {
        const { order, lines } = await outboundOrderApi.get(orderId);
        soId = order.sales_order_id;
        existingLines = lines;
        setExpectedUpdatedAt(order.updated_at);
        form.setFieldsValue({ note: order.note ?? undefined });
      } else {
        form.resetFields();
        setExpectedUpdatedAt(null);
      }

      const avaRes = await outboundOrderApi.outboundableLines(soId);

      // 候选行(可发集):默认未选,数量预填可发量。
      const byLine = new Map<number, BuilderRow>();
      avaRes.items.forEach((p) => {
        byLine.set(p.sales_order_line_id, {
          sales_order_line_id: p.sales_order_line_id,
          name_snapshot: p.name_snapshot,
          spec_text_snapshot: p.spec_text_snapshot,
          unit_snapshot: p.unit_snapshot,
          ordered_qty: Number(p.ordered_qty),
          outbound_qty: Number(p.outbound_qty),
          available_qty: Number(p.available_qty),
          selected: false,
          qty: Number(p.available_qty),
        });
      });

      // 既有出库行覆盖候选行(勾选 + 回填)。草稿未扣库存 ⇒ 可发已含本单额度,无需排除自身。
      existingLines.forEach((l) => {
        const existing = byLine.get(l.sales_order_line_id);
        byLine.set(l.sales_order_line_id, {
          sales_order_line_id: l.sales_order_line_id,
          existing: true,
          name_snapshot: l.name_snapshot,
          spec_text_snapshot: l.spec_text_snapshot,
          unit_snapshot: l.unit_snapshot,
          ordered_qty: existing?.ordered_qty,
          outbound_qty: existing?.outbound_qty,
          available_qty: existing?.available_qty,
          selected: true,
          qty: Number(l.qty),
        });
      });

      setRows(Array.from(byLine.values()));
    } catch (e) {
      message.error(resolveBizError(e, "加载可发行失败"));
      onClose();
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, orderId, salesOrderId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const patchRow = (lid: number, patch: Partial<BuilderRow>) =>
    setRows((rs) => rs.map((r) => (r.sales_order_line_id === lid ? { ...r, ...patch } : r)));

  // 本次可发上限 = 可发量(草稿不扣库存,故不排除自身);可发未知则不设客户端上限,交后端为准。
  const maxIssuable = (r: BuilderRow): number | undefined => r.available_qty;

  const selectedRows = useMemo(() => rows.filter((r) => r.selected), [rows]);
  const totalQty = useMemo(
    () => selectedRows.reduce((s, r) => s + (r.qty || 0), 0),
    [selectedRows],
  );

  async function onSubmit() {
    let header: { note?: string };
    try {
      header = await form.validateFields();
    } catch {
      return;
    }
    if (selectedRows.length === 0) {
      message.error("至少勾选一行");
      return;
    }
    for (const r of selectedRows) {
      if (!r.qty || r.qty <= 0) {
        message.error(`「${r.name_snapshot}」数量需大于 0`);
        return;
      }
      const max = maxIssuable(r);
      if (max !== undefined && r.qty > max) {
        message.error(`「${r.name_snapshot}」数量超过可发 ${formatQty(max)}`);
        return;
      }
    }

    const lines: OutboundOrderLineIn[] = selectedRows.map((r, i) => ({
      sales_order_line_id: r.sales_order_line_id,
      qty: r.qty,
      sort_order: i,
    }));
    const note = header.note?.trim() || null;

    setSaving(true);
    try {
      if (mode === "create") {
        const { order } = await outboundOrderApi.create({
          shipment_id: shipmentId as number,
          sales_order_id: salesOrderId,
          note,
          lines,
        });
        message.success(`已生成出库单 ${order.no}`);
      } else if (orderId) {
        await outboundOrderApi.update(orderId, {
          note,
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

  // 数字列走共享 NumCell(DESIGN 数字列)。muted=参考的次要数字弱化,
  // strong=「可发」是本次录入的约束基准,保持强调。
  const refCol = (title: string, get: (r: BuilderRow) => number | undefined, strong = false) => ({
    title,
    key: title,
    width: 82,
    align: "right" as const,
    render: (_: unknown, r: BuilderRow) => <NumCell value={get(r)} muted={!strong} strong={strong} />,
  });

  const columns: ColumnsType<BuilderRow> = [
    {
      title: "",
      key: "sel",
      width: 40,
      render: (_, r) => (
        <Checkbox
          checked={r.selected}
          onChange={(e) => patchRow(r.sales_order_line_id, { selected: e.target.checked })}
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
    {
      title: "发货参考",
      align: "center",
      children: [
        refCol("订购", (r) => r.ordered_qty),
        refCol("已出库", (r) => r.outbound_qty),
        refCol("可发", (r) => r.available_qty, true),
      ],
    },
    {
      title: "本次数量",
      key: "qty",
      width: 140,
      render: (_, r) => {
        const max = maxIssuable(r);
        const over = max !== undefined && r.qty > max;
        return (
          <div>
            <InputNumber
              min={0.001}
              status={over ? "error" : undefined}
              value={r.qty}
              onChange={(v) =>
                // 一动数量即自动勾选该行;取消勾选仍走复选框。
                patchRow(r.sales_order_line_id, { qty: Number(v) || 0, selected: true })
              }
              style={{ width: "100%" }}
            />
            {over && (
              <Typography.Text type="danger" style={{ fontSize: 12 }}>
                超过可发 {formatQty(max!)}
              </Typography.Text>
            )}
          </div>
        );
      },
    },
  ];

  return (
    <Drawer
      title={mode === "create" ? "添加出库单" : "编辑出库单"}
      open={open}
      onClose={onClose}
      width="min(900px, 96vw)"
      destroyOnClose
      footer={
        <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
          <span style={{ fontWeight: 600, color: colors.navy }}>
            已选 {selectedRows.length} 行 · 合计件数 {formatQty(totalQty)}
          </span>
          <Space>
            <Button onClick={onClose} disabled={saving}>
              取消
            </Button>
            <Button type="primary" loading={saving} onClick={onSubmit}>
              {mode === "create" ? "生成出库单" : "保存"}
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
              <Form.Item name="note" label="备注" style={{ marginBottom: 12 }}>
                <Input.TextArea rows={2} placeholder="选填" />
              </Form.Item>
            </Form>
          </div>

          <div style={{ marginBottom: 8, color: colors.muted, fontSize: 12 }}>
            勾选可发行、录本次出库数量(受可发量约束)。草稿不扣库存,确认装柜时才扣减并生成应收。
          </div>
          <Table<BuilderRow>
            rowKey="sales_order_line_id"
            size="small"
            columns={columns}
            dataSource={rows}
            pagination={false}
            scroll={{ x: 780 }}
            locale={{ emptyText: "该销售单当前无可发行" }}
          />
        </>
      )}
    </Drawer>
  );
}
