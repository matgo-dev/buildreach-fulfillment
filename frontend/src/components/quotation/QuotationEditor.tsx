"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
  Col,
  DatePicker,
  Divider,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
} from "antd";
import { colors } from "@/lib/tokens";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { display } from "@/lib/i18n";
import { formatMoney } from "@/lib/format";
import { resolveBizError } from "@/lib/errorMessages";
import { PageLoading } from "@/components/common/PageLoading";
import { catalogApi, specDisplayText } from "@/lib/catalog";
import { quotationApi, type QuotationSaveBody } from "@/lib/quotation";
import { customerApi, type CustomerListItem } from "@/lib/customer";
import { ProductPickerDrawer, type PickedSku } from "@/components/quotation/ProductPickerDrawer";

import { CURRENCY_OPTIONS } from "@/lib/currencies";
import { QUOTE_LANGUAGE_OPTIONS } from "@/lib/quote-languages";

/** 编辑器内的行(前端本地态)。_key 稳定 rowKey;id 有值=已存在行(对账更新)。
 *  spec_text/unit 是选中 SKU 后派生的**只读预览**(展示 label,非用户输入);
 *  权威值由后端保存时 compose_line_snapshot 冻结,此处只为录入时给确认反馈。 */
interface EditLine {
  _key: string;
  id?: number;
  sku_id?: number;
  sku_label?: string;
  spec_text?: string;
  unit?: string;
  unit_price: number;
  qty: number;
  remark?: string;
}

let _seq = 0;
const newKey = () => `l${++_seq}`;

export function QuotationEditor({ mode, orderId }: { mode: "create" | "edit"; orderId?: number }) {
  const router = useRouter();
  const { message } = App.useApp();
  const [form] = Form.useForm();

  const [customers, setCustomers] = useState<{ id: number; name: string }[]>([]);
  const [salespeople, setSalespeople] = useState<{ id: number; name: string }[]>([]);
  const [lines, setLines] = useState<EditLine[]>([]);
  const [unitLabels, setUnitLabels] = useState<Map<string, string>>(new Map());
  const [expectedUpdatedAt, setExpectedUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(mode === "edit");
  const [saving, setSaving] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);

  const load = useCallback(async () => {
    try {
      const [custs, sps, units] = await Promise.all([
        customerApi.list({ status: "ACTIVE", size: 100 }),
        quotationApi.usersSelectable(),
        catalogApi.units(),
      ]);
      setCustomers(custs.items.map((c: CustomerListItem) => ({ id: c.id, name: c.name })));
      setSalespeople(sps);
      // 售卖单位 code→展示 label(与后端 unit_snapshot 口径一致:units.label_i18n)。
      setUnitLabels(new Map(units.items.map((u) => [u.code, display(u.label_i18n)])));
      if (mode === "edit" && orderId) {
        const { order, lines: ls } = await quotationApi.get(orderId);
        if (order.status !== "DRAFT") {
          message.warning("仅草稿可编辑,已跳转详情");
          router.replace(`/sales/quotations/${orderId}`);
          return;
        }
        setExpectedUpdatedAt(order.updated_at);
        // 存量单据的客户可能已停用(不在 ACTIVE 下拉里):补进选项,保证回显与"不换客户可保存"。
        setCustomers((prev) =>
          prev.some((c) => c.id === order.customer_id)
            ? prev
            : [...prev, { id: order.customer_id, name: order.customer_display ?? `#${order.customer_id}` }],
        );
        form.setFieldsValue({
          customer_id: order.customer_id,
          salesperson_id: order.salesperson_id,
          currency: order.currency,
          language: order.language,
          summary: order.summary,
          remark: order.remark,
          valid_until: order.valid_until ? dayjs(order.valid_until) : undefined,
        });
        setLines(
          ls.map((l) => ({
            _key: newKey(),
            id: l.id,
            sku_id: l.sku_id,
            sku_label: l.name_snapshot,
            spec_text: l.spec_text_snapshot || undefined,
            unit: l.unit_snapshot || undefined,
            unit_price: Number(l.unit_price),
            qty: Number(l.qty),
            remark: l.remark ?? undefined,
          })),
        );
      }
    } catch (e) {
      message.error(resolveBizError(e, "加载失败"));
    } finally {
      setLoading(false);
    }
  }, [mode, orderId, form, message, router]);

  useEffect(() => {
    load();
  }, [load]);

  const patchLine = (key: string, patch: Partial<EditLine>) =>
    setLines((ls) => ls.map((l) => (l._key === key ? { ...l, ...patch } : l)));

  // 已在单据上的 SKU(挑货抽屉据此标「已添加」,不重复加,改数量在行内)。
  const addedSkuIds = useMemo(
    () => new Set(lines.map((l) => l.sku_id).filter((x): x is number => x != null)),
    [lines],
  );

  // 从挑货抽屉加一行:立刻带出名称/单位(单位 label 与快照口径一致),再异步拉合并规格预览。
  async function addLineFromSku(p: PickedSku) {
    const key = newKey();
    setLines((ls) => [
      ...ls,
      { _key: key, sku_id: p.sku_id, sku_label: `${p.sku_code} · ${p.name}`, unit: unitLabels.get(p.unit) ?? p.unit, unit_price: 0, qty: 1 },
    ]);
    try {
      const detail = await catalogApi.getSku(p.sku_id); // spec_display = SPU∪SKU 后端单一解析
      patchLine(key, { spec_text: specDisplayText(detail.spec_display) || undefined });
    } catch {
      /* 规格预览失败不阻断录入;保存时后端仍会按 order_lang 冻结快照 */
    }
  }

  const total = useMemo(
    () => lines.reduce((s, l) => s + (l.unit_price || 0) * (l.qty || 0), 0),
    [lines],
  );

  async function onSave() {
    let header;
    try {
      header = await form.validateFields();
    } catch {
      return;
    }
    if (lines.length === 0) {
      message.error("至少添加一行");
      return;
    }
    if (lines.some((l) => !l.sku_id)) {
      message.error("每行都需选择商品");
      return;
    }
    const body: QuotationSaveBody = {
      customer_id: header.customer_id,
      currency: header.currency,
      salesperson_id: header.salesperson_id,
      language: header.language,
      summary: header.summary ?? null,
      remark: header.remark ?? null,
      valid_until: header.valid_until ? header.valid_until.format("YYYY-MM-DD") : null,
      lines: lines.map((l, i) => ({
        id: l.id,
        sku_id: l.sku_id as number,
        unit_price: l.unit_price,
        qty: l.qty,
        remark: l.remark ?? null,
        sort_order: i,
      })),
    };
    setSaving(true);
    try {
      const saved =
        mode === "create"
          ? await quotationApi.create(body)
          : await quotationApi.update(orderId as number, {
              ...body,
              expected_updated_at: expectedUpdatedAt as string,
            });
      message.success("已保存");
      router.push(`/sales/quotations/${saved.id}`);
    } catch (e) {
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  const columns: ColumnsType<EditLine> = [
    {
      title: "商品",
      key: "sku",
      render: (_, r) => <span>{r.sku_label}</span>,
    },
    {
      title: "规格",
      key: "spec",
      ellipsis: true,
      render: (_, r) => r.spec_text || <span style={{ color: colors.muted }}>—</span>,
    },
    {
      title: "单位",
      key: "unit",
      width: 80,
      render: (_, r) => r.unit || <span style={{ color: colors.muted }}>—</span>,
    },
    {
      title: "数量",
      key: "qty",
      width: 120,
      render: (_, r) => (
        <InputNumber min={0.001} value={r.qty} onChange={(v) => patchLine(r._key, { qty: Number(v) || 0 })} style={{ width: "100%" }} />
      ),
    },
    {
      title: "单价",
      key: "unit_price",
      width: 130,
      render: (_, r) => (
        <InputNumber min={0} value={r.unit_price} onChange={(v) => patchLine(r._key, { unit_price: Number(v) || 0 })} style={{ width: "100%" }} />
      ),
    },
    {
      title: "金额",
      key: "amount",
      width: 120,
      align: "right",
      render: (_, r) => formatMoney((r.unit_price || 0) * (r.qty || 0)),
    },
    {
      title: "明细备注",
      key: "remark",
      width: 180,
      render: (_, r) => (
        <Input value={r.remark} placeholder="选填" onChange={(e) => patchLine(r._key, { remark: e.target.value })} />
      ),
    },
    {
      title: "",
      key: "del",
      width: 44,
      render: (_, r) => (
        <Button type="text" danger icon={<DeleteOutlined />} onClick={() => setLines((ls) => ls.filter((l) => l._key !== r._key))} />
      ),
    },
  ];

  if (loading) return <PageLoading />;

  return (
    <Card
      title={mode === "create" ? "新建报价" : "编辑报价"}
      extra={
        <Space>
          <Button onClick={() => router.back()}>取消</Button>
          <Button type="primary" loading={saving} onClick={onSave}>
            保存
          </Button>
        </Space>
      }
    >
      {/* 表头字段:DESIGN §6 表单正文内部最大宽度,按 1–2 列网格分组,不铺满超宽屏。 */}
      <div style={{ maxWidth: 860 }}>
        <Form form={form} layout="vertical" initialValues={{ currency: "USD", language: "zh" }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="customer_id" label="客户" rules={[{ required: true, message: "选择客户" }]}>
                <Select
                  showSearch
                  placeholder="选择客户"
                  optionFilterProp="label"
                  options={customers.map((c) => ({ value: c.id, label: c.name }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="salesperson_id" label="报价人">
                <Select
                  showSearch
                  placeholder="默认=建单人"
                  optionFilterProp="label"
                  allowClear
                  options={salespeople.map((s) => ({ value: s.id, label: s.name }))}
                />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="currency" label="币种" rules={[{ required: true }]}>
                <Select options={CURRENCY_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="language" label="语言">
                <Select options={QUOTE_LANGUAGE_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="valid_until" label="有效期">
                <DatePicker style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="summary" label="摘要">
            <Input maxLength={180} placeholder="一句话主题(选填)" />
          </Form.Item>
          <Form.Item name="remark" label="备注" style={{ marginBottom: 0 }}>
            <Input.TextArea rows={2} placeholder="说明 / 条款(选填)" />
          </Form.Item>
        </Form>
      </div>

      <Divider titlePlacement="left" plain style={{ marginTop: 24, marginBottom: 12 }}>
        报价明细
      </Divider>
      <Table<EditLine>
        rowKey="_key"
        size="small"
        columns={columns}
        dataSource={lines}
        pagination={false}
        locale={{ emptyText: "点击「添加商品」从商品库选货" }}
        footer={() => (
          <Space style={{ width: "100%", justifyContent: "space-between" }}>
            <Button type="dashed" icon={<PlusOutlined />} onClick={() => setPickerOpen(true)}>
              添加商品
            </Button>
            <span style={{ fontWeight: 600, color: colors.navy }}>
              合计 {formatMoney(total)}
            </span>
          </Space>
        )}
      />

      <ProductPickerDrawer
        open={pickerOpen}
        addedSkuIds={addedSkuIds}
        onClose={() => setPickerOpen(false)}
        onPick={addLineFromSku}
      />
    </Card>
  );
}
