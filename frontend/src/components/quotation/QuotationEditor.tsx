"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  App,
  Button,
  Card,
  DatePicker,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Spin,
  Table,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, PlusOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { api } from "@/lib/api";
import { display } from "@/lib/i18n";
import { quotationApi, type QuotationSaveBody } from "@/lib/quotation";
import { SkuPicker } from "@/components/quotation/SkuPicker";

const CURRENCIES = ["USD", "CNY", "KES", "TZS", "EUR"];
const LANGUAGES = [
  { value: "zh", label: "中文" },
  { value: "en", label: "English" },
  { value: "sw", label: "Kiswahili" },
];

interface CustomerLite {
  id: number;
  name_i18n: Record<string, string>;
}

/** 编辑器内的行(前端本地态)。_key 稳定 rowKey;id 有值=已存在行(对账更新)。 */
interface EditLine {
  _key: string;
  id?: number;
  sku_id?: number;
  sku_label?: string;
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

  const [customers, setCustomers] = useState<CustomerLite[]>([]);
  const [salespeople, setSalespeople] = useState<{ id: number; name: string }[]>([]);
  const [lines, setLines] = useState<EditLine[]>([]);
  const [expectedUpdatedAt, setExpectedUpdatedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(mode === "edit");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      const [custs, sps] = await Promise.all([
        api.get<CustomerLite[]>("/api/v1/customers"),
        quotationApi.usersSelectable(),
      ]);
      setCustomers(custs);
      setSalespeople(sps);
      if (mode === "edit" && orderId) {
        const { order, lines: ls } = await quotationApi.get(orderId);
        if (order.status !== "DRAFT") {
          message.warning("仅草稿可编辑,已跳转详情");
          router.replace(`/sales/quotations/${orderId}`);
          return;
        }
        setExpectedUpdatedAt(order.updated_at);
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
            unit_price: Number(l.unit_price),
            qty: Number(l.qty),
            remark: l.remark ?? undefined,
          })),
        );
      }
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [mode, orderId, form, message, router]);

  useEffect(() => {
    load();
  }, [load]);

  const patchLine = (key: string, patch: Partial<EditLine>) =>
    setLines((ls) => ls.map((l) => (l._key === key ? { ...l, ...patch } : l)));

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
      message.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  const columns: ColumnsType<EditLine> = [
    {
      title: "商品",
      key: "sku",
      render: (_, r) =>
        r.sku_id ? (
          <Space size="small">
            <span>{r.sku_label}</span>
            <Button type="link" size="small" onClick={() => patchLine(r._key, { sku_id: undefined, sku_label: undefined })}>
              重选
            </Button>
          </Space>
        ) : (
          <SkuPicker
            onPick={(p) => p && patchLine(r._key, { sku_id: p.sku_id, sku_label: `${p.sku_code} · ${p.name}` })}
          />
        ),
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
      render: (_, r) => ((r.unit_price || 0) * (r.qty || 0)).toLocaleString(undefined, { minimumFractionDigits: 2 }),
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

  if (loading) return <Spin style={{ display: "block", marginTop: 80 }} />;

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
      <Form form={form} layout="vertical" initialValues={{ currency: "USD", language: "zh" }}>
        <Space size="large" wrap>
          <Form.Item name="customer_id" label="客户" rules={[{ required: true, message: "选择客户" }]} style={{ width: 240 }}>
            <Select
              showSearch
              placeholder="选择客户"
              optionFilterProp="label"
              options={customers.map((c) => ({ value: c.id, label: display(c.name_i18n) }))}
            />
          </Form.Item>
          <Form.Item name="salesperson_id" label="报价人" style={{ width: 160 }}>
            <Select
              showSearch
              placeholder="默认=建单人"
              optionFilterProp="label"
              allowClear
              options={salespeople.map((s) => ({ value: s.id, label: s.name }))}
            />
          </Form.Item>
          <Form.Item name="currency" label="币种" rules={[{ required: true }]} style={{ width: 110 }}>
            <Select options={CURRENCIES.map((c) => ({ value: c, label: c }))} />
          </Form.Item>
          <Form.Item name="language" label="语言" style={{ width: 130 }}>
            <Select options={LANGUAGES} />
          </Form.Item>
          <Form.Item name="valid_until" label="有效期" style={{ width: 160 }}>
            <DatePicker style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item name="summary" label="摘要" style={{ width: 260 }}>
            <Input maxLength={180} placeholder="一句话主题(选填)" />
          </Form.Item>
        </Space>
        <Form.Item name="remark" label="备注">
          <Input.TextArea rows={2} placeholder="说明 / 条款(选填)" />
        </Form.Item>
      </Form>

      <Table<EditLine>
        rowKey="_key"
        size="small"
        columns={columns}
        dataSource={lines}
        pagination={false}
        locale={{ emptyText: "点击下方「加行」添加商品" }}
        footer={() => (
          <Space style={{ width: "100%", justifyContent: "space-between" }}>
            <Button icon={<PlusOutlined />} onClick={() => setLines((ls) => [...ls, { _key: newKey(), unit_price: 0, qty: 1 }])}>
              加行
            </Button>
            <span style={{ fontWeight: 600 }}>
              合计:{total.toLocaleString(undefined, { minimumFractionDigits: 2 })}
            </span>
          </Space>
        )}
      />
    </Card>
  );
}
