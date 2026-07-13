"use client";
import { useEffect, useMemo, useState } from "react";
import {
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Button,
  Space,
  Divider,
  Typography,
  App,
} from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import {
  catalogApi,
  SkuOut,
  SkuWithImages,
  SkuSpecItemIn,
  SpecSuggestion,
  SpecOption,
  SpecValueType,
  UnitOut,
} from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { ImageZone } from "@/components/catalog/ImageManager";
import { colors } from "@/lib/tokens";

const { Text } = Typography;

// enum 单元的取值意图:选既有选项 code,或 inline 新增一个选项(提交时后端生成 v_ code)。
type EnumMode =
  | { kind: "existing"; code?: string }
  | { kind: "new"; zh: string; en?: string };

interface TemplateRow {
  fromTemplate: true;
  key: string;
  label: string;
  valueType: SpecValueType;
  unit: string; // 模板计量单位,只读展示(§11 Part B)
  options: SpecOption[];
  str?: string;
  num?: number | null;
  enumMode?: EnumMode;
}
interface CustomRow {
  fromTemplate: false;
  localId: string;
  labelZh: string;
  labelEn?: string;
  unit?: string;
  value: string;
}
type Row = TemplateRow | CustomRow;

function toValueString(v: SkuOut["spec_jsonb"][number]["value"]): string {
  return typeof v === "object" ? display(v) : String(v);
}

/** enum 取值单元:既有选项下拉 + 底部「新增选项」逃生口(zh 必填 / en 选填)。 */
function EnumCell({
  row,
  onChange,
}: {
  row: TemplateRow;
  onChange: (m: EnumMode) => void;
}) {
  const [newZh, setNewZh] = useState("");
  const [newEn, setNewEn] = useState("");

  const options = row.options.map((o) => ({ value: o.code, label: display(o.label_i18n) || o.code }));
  // 编辑时既有 code 不在 options(极少),补一个回退项避免显示空。
  if (row.enumMode?.kind === "existing" && row.enumMode.code) {
    const code = row.enumMode.code;
    if (!row.options.some((o) => o.code === code)) {
      options.push({ value: code, label: code });
    }
  }
  const pendingVal = "__pending_new__";
  if (row.enumMode?.kind === "new") {
    options.push({ value: pendingVal, label: `新增:${row.enumMode.zh}` });
  }

  const value =
    row.enumMode?.kind === "existing"
      ? row.enumMode.code
      : row.enumMode?.kind === "new"
      ? pendingVal
      : undefined;

  return (
    <Select
      style={{ width: "100%" }}
      placeholder="选择或新增"
      allowClear
      value={value}
      options={options}
      onChange={(v) => {
        if (v === undefined) onChange({ kind: "existing", code: undefined });
        else if (v !== pendingVal) onChange({ kind: "existing", code: v as string });
      }}
      popupRender={(menu) => (
        <>
          {menu}
          <Divider style={{ margin: "8px 0" }} />
          <Space style={{ padding: "0 8px 8px" }} wrap>
            <Input
              size="small"
              placeholder="新选项(中文)"
              style={{ width: 130 }}
              value={newZh}
              onChange={(e) => setNewZh(e.target.value)}
            />
            <Input
              size="small"
              placeholder="英文(选填)"
              style={{ width: 110 }}
              value={newEn}
              onChange={(e) => setNewEn(e.target.value)}
            />
            <Button
              size="small"
              type="link"
              icon={<PlusOutlined />}
              disabled={!newZh.trim()}
              onClick={() => {
                onChange({ kind: "new", zh: newZh.trim(), en: newEn.trim() || undefined });
                setNewZh("");
                setNewEn("");
              }}
            >
              新增
            </Button>
          </Space>
        </>
      )}
    />
  );
}

export function SkuForm({
  open,
  spuId,
  categoryCode,
  sku,
  onClose,
  onSaved,
}: {
  open: boolean;
  spuId: number;
  categoryCode: string;
  sku?: SkuWithImages;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [units, setUnits] = useState<UnitOut[]>([]);
  const [rows, setRows] = useState<Row[]>([]);
  const [imageKeys, setImageKeys] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [customSeq, setCustomSeq] = useState(0);

  useEffect(() => {
    if (!open) return;
    catalogApi.units().then((r) => setUnits(r.items)).catch(() => setUnits([]));
    form.setFieldsValue(
      sku
        ? { name_zh: display(sku.name_i18n), unit: sku.unit, reference_price: sku.reference_price ?? undefined }
        : { name_zh: "", unit: undefined, reference_price: undefined },
    );
    setImageKeys(sku ? sku.images.map((i) => i.image_key) : []);

    // 模板全量铺开:每个 attribute 一行,已有值回填。
    catalogApi
      .specSuggestions(categoryCode)
      .then((r) => setRows(buildRows(r.items, sku)))
      .catch(() => setRows(buildRows([], sku)));
  }, [open, sku, categoryCode, form]);

  function updateTemplate(key: string, patch: Partial<TemplateRow>) {
    setRows((rs) =>
      rs.map((r) => (r.fromTemplate && r.key === key ? { ...r, ...patch } : r)),
    );
  }
  function updateCustom(localId: string, patch: Partial<CustomRow>) {
    setRows((rs) =>
      rs.map((r) => (!r.fromTemplate && r.localId === localId ? { ...r, ...patch } : r)),
    );
  }
  function addCustom() {
    setRows((rs) => [
      ...rs,
      { fromTemplate: false, localId: `c${customSeq}`, labelZh: "", value: "" },
    ]);
    setCustomSeq((n) => n + 1);
  }
  function removeCustom(localId: string) {
    setRows((rs) => rs.filter((r) => r.fromTemplate || r.localId !== localId));
  }

  function collectSpecItems(): SkuSpecItemIn[] | null {
    const items: SkuSpecItemIn[] = [];
    for (const r of rows) {
      if (r.fromTemplate) {
        if (r.valueType === "enum") {
          if (r.enumMode?.kind === "existing" && r.enumMode.code) {
            items.push({ key: r.key, value: r.enumMode.code });
          } else if (r.enumMode?.kind === "new" && r.enumMode.zh.trim()) {
            items.push({
              key: r.key,
              label_i18n: { zh: r.enumMode.zh.trim(), ...(r.enumMode.en ? { en: r.enumMode.en } : {}) },
            });
          }
          // 空 → 不提交
        } else if (r.valueType === "number") {
          if (r.num !== undefined && r.num !== null) items.push({ key: r.key, value: r.num });
        } else {
          if (r.str && r.str.trim()) items.push({ key: r.key, value: r.str.trim() });
        }
      } else {
        if (!r.value.trim()) continue; // 空值行不提交
        if (!r.labelZh.trim()) {
          message.error("手输规格需填中文标签");
          return null;
        }
        items.push({
          label_i18n: { zh: r.labelZh.trim(), ...(r.labelEn?.trim() ? { en: r.labelEn.trim() } : {}) },
          unit: r.unit?.trim() || null,
          value: r.value.trim(),
        });
      }
    }
    return items;
  }

  async function onSubmit() {
    const v = await form.validateFields();
    const spec_items = collectSpecItems();
    if (spec_items === null) return;
    setSaving(true);
    try {
      const body = {
        spu_id: spuId,
        unit: v.unit,
        name_i18n: { zh: v.name_zh.trim() },
        reference_price: v.reference_price ?? null,
        spec_items,
        images: imageKeys.map((k, i) => ({ image_key: k, sort_order: i })),
      };
      if (sku) await catalogApi.updateSku(sku.id, body);
      else await catalogApi.createSku(body);
      message.success("已保存");
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  const unitOptions = useMemo(
    () => units.map((u) => ({ value: u.code, label: `${display(u.label_i18n) || u.code} (${u.code})` })),
    [units],
  );

  const templateRows = rows.filter((r): r is TemplateRow => r.fromTemplate);
  const customRows = rows.filter((r): r is CustomRow => !r.fromTemplate);

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={680}
      title={sku ? "编辑 SKU" : "新建 SKU"}
      extra={
        <Space>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} onClick={onSubmit}>
            保存
          </Button>
        </Space>
      }
    >
      <Form form={form} layout="vertical">
        <Form.Item
          name="name_zh"
          label="名称(中文)"
          rules={[
            { required: true, message: "中文名必填" },
            {
              validator: (_, v) =>
                v && v.trim() ? Promise.resolve() : Promise.reject(new Error("禁空串")),
            },
          ]}
        >
          <Input placeholder="如:镀锌钢管 DN50" maxLength={120} />
        </Form.Item>
        <Form.Item name="unit" label="售卖单位" rules={[{ required: true, message: "请选择单位" }]}>
          <Select
            placeholder="选择单位"
            showSearch
            optionFilterProp="label"
            options={unitOptions}
            style={{ maxWidth: 260 }}
            notFoundContent="无可用单位(去单位管理台新增)"
          />
        </Form.Item>
        <Form.Item label="内部采购参考价(仅商品管理可见)" name="reference_price">
          <InputNumber style={{ width: 200 }} precision={2} min={0} placeholder="0.00" addonBefore="¥" />
        </Form.Item>
      </Form>

      <Divider titlePlacement="left" plain style={{ marginTop: 8 }}>
        SKU 图(可选)
      </Divider>
      <div style={{ marginBottom: 4, fontSize: 12, color: colors.muted }}>
        该 SKU 有专属图时上传,否则自动用商品主图。
      </div>
      <ImageZone title="SKU 图" keys={imageKeys} max={6} onChange={setImageKeys} />

      <Divider titlePlacement="left" plain style={{ marginTop: 8 }}>
        规格(按类目模板铺开,留空不提交)
      </Divider>

      {templateRows.length === 0 && customRows.length === 0 && (
        <Text type="secondary">该类目暂无规格模板,可用下方「新增属性」手动补充。</Text>
      )}

      <Space direction="vertical" size={10} style={{ width: "100%" }}>
        {templateRows.map((r) => (
          <div key={r.key} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 150, textAlign: "right", color: colors.muted }}>
              {r.label}
              {r.unit ? <Text type="secondary"> [{r.unit}]</Text> : null}
            </div>
            <div style={{ flex: 1 }}>
              {r.valueType === "enum" ? (
                <EnumCell row={r} onChange={(enumMode) => updateTemplate(r.key, { enumMode })} />
              ) : r.valueType === "number" ? (
                <InputNumber
                  style={{ width: "100%" }}
                  value={r.num ?? undefined}
                  addonAfter={r.unit || undefined}
                  onChange={(num) => updateTemplate(r.key, { num: num as number | null })}
                />
              ) : (
                <Input
                  value={r.str ?? ""}
                  onChange={(e) => updateTemplate(r.key, { str: e.target.value })}
                />
              )}
            </div>
          </div>
        ))}

        {customRows.map((r) => (
          <div key={r.localId} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Input
              style={{ width: 120 }}
              placeholder="属性名(中文)"
              value={r.labelZh}
              onChange={(e) => updateCustom(r.localId, { labelZh: e.target.value })}
            />
            <Input
              style={{ width: 96 }}
              placeholder="英文(选填)"
              value={r.labelEn}
              onChange={(e) => updateCustom(r.localId, { labelEn: e.target.value })}
            />
            <Input
              style={{ flex: 1 }}
              placeholder="值"
              value={r.value}
              onChange={(e) => updateCustom(r.localId, { value: e.target.value })}
            />
            <Input
              style={{ width: 80 }}
              placeholder="单位"
              value={r.unit}
              onChange={(e) => updateCustom(r.localId, { unit: e.target.value })}
            />
            <Button type="text" danger icon={<DeleteOutlined />} onClick={() => removeCustom(r.localId)} />
          </div>
        ))}
      </Space>

      <Button type="dashed" icon={<PlusOutlined />} onClick={addCustom} style={{ marginTop: 12 }}>
        新增属性(类目缺轴时用)
      </Button>
    </Drawer>
  );
}

function buildRows(suggestions: SpecSuggestion[], sku?: SkuOut): Row[] {
  const byKey = new Map<string, SkuOut["spec_jsonb"][number]>();
  (sku?.spec_jsonb ?? []).forEach((i) => byKey.set(i.key, i));

  const rows: Row[] = suggestions.map((s) => {
    const existing = byKey.get(s.key);
    byKey.delete(s.key);
    const base: TemplateRow = {
      fromTemplate: true,
      key: s.key,
      label: display(s.label_i18n) || s.key,
      valueType: s.value_type,
      unit: s.unit || "",
      options: s.options ?? [],
    };
    if (!existing) return base;
    if (s.value_type === "enum") {
      base.enumMode = { kind: "existing", code: toValueString(existing.value) };
    } else if (s.value_type === "number") {
      base.num = Number(existing.value);
    } else {
      base.str = toValueString(existing.value);
    }
    return base;
  });

  // 模板里没有、但 SKU 已存的 key(极少):作只读字符串行保留,避免编辑保存时丢值。
  byKey.forEach((item, key) => {
    rows.push({
      fromTemplate: true,
      key,
      label: key,
      valueType: "string",
      unit: "",
      options: [],
      str: toValueString(item.value),
    });
  });

  return rows;
}
