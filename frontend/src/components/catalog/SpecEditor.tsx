"use client";
import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { Input, InputNumber, Select, Button, Space, Typography, App } from "antd";
import type { MessageInstance } from "antd/es/message/interface";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";
import {
  catalogApi,
  SpecItem,
  SkuSpecItemIn,
  SpecScope,
  SpecSuggestion,
  SpecOption,
  SpecValueType,
} from "@/lib/catalog";
import { display } from "@/lib/i18n";
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

function toValueString(v: SpecItem["value"]): string {
  return typeof v === "object" && v !== null ? display(v) : String(v);
}

const ENUM_ADD = "__enum_add__"; // 「新增:X」确认项的哨兵值
const ENUM_STAGED = "__enum_staged__"; // 已暂存的新值(选中态)的哨兵值

/** enum 取值单元:可输入下拉(combobox)。输入即过滤既有选项;无匹配时出现「新增:X」
 *  确认项——点它才落新值(不静默追加,守住受控值域)。提交后由后端生成稳定 code。 */
function EnumCell({
  row,
  onChange,
}: {
  row: TemplateRow;
  onChange: (m: EnumMode) => void;
}) {
  const [search, setSearch] = useState("");

  const base = row.options.map((o) => ({ value: o.code, label: display(o.label_i18n) || o.code }));
  // 编辑时既有 code 不在 options(极少),补一个回退项避免显示空。
  if (row.enumMode?.kind === "existing" && row.enumMode.code) {
    const code = row.enumMode.code;
    if (!row.options.some((o) => o.code === code)) {
      base.push({ value: code, label: code });
    }
  }
  // 已暂存的新值(尚未落库),作选中项展示。
  if (row.enumMode?.kind === "new") {
    base.push({ value: ENUM_STAGED, label: `新增:${row.enumMode.zh}` });
  }
  // 正在输入且与既有 label 无精确匹配 → 追加「新增:X」确认项。
  const q = search.trim();
  const exact = !!q && base.some((o) => o.label.toLowerCase() === q.toLowerCase());
  const options = q && !exact ? [...base, { value: ENUM_ADD, label: `新增:"${q}"` }] : base;

  const value =
    row.enumMode?.kind === "existing"
      ? row.enumMode.code
      : row.enumMode?.kind === "new"
      ? ENUM_STAGED
      : undefined;

  return (
    <Select
      style={{ width: "100%" }}
      showSearch
      allowClear
      placeholder="选择,或输入新值后点「新增」"
      value={value}
      options={options}
      searchValue={search}
      onSearch={setSearch}
      filterOption={(input, opt) =>
        String(opt?.label ?? "").toLowerCase().includes(input.trim().toLowerCase())
      }
      onChange={(v) => {
        setSearch("");
        if (v === undefined) onChange({ kind: "existing", code: undefined });
        else if (v === ENUM_ADD) onChange({ kind: "new", zh: q });
        else if (v !== ENUM_STAGED) onChange({ kind: "existing", code: v as string });
      }}
      onBlur={() => setSearch("")}
    />
  );
}

function buildRows(suggestions: SpecSuggestion[], scope: SpecScope, initialSpec?: SpecItem[]): Row[] {
  const byKey = new Map<string, SpecItem>();
  (initialSpec ?? []).forEach((i) => byKey.set(i.key, i));

  const rows: Row[] = suggestions
    .filter((s) => s.scope === scope) // 只铺本层(SPU 产品级 / SKU 变体轴)的属性
    .map((s) => {
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

  // 模板里没有、但已存值的 key(极少):作只读字符串行保留,避免编辑保存时丢值。
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

function collectSpecItems(rows: Row[], message: MessageInstance): SkuSpecItemIn[] | null {
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

export interface SpecEditorHandle {
  /** 汇总本编辑器规格为写入项;手输行缺中文标签时返回 null(阻断提交)。 */
  collect: () => SkuSpecItemIn[] | null;
}

/** 类目模板驱动的规格编辑器(SPU 产品级 / SKU 变体轴共用,按 scope 分渲染)。
 *  父层自管 section 标题;本组件只出「行 + 新增属性」。提交时父层经 ref.collect() 取值。 */
export const SpecEditor = forwardRef<
  SpecEditorHandle,
  {
    open: boolean;
    categoryCode: string;
    scope: SpecScope;
    initialSpec?: SpecItem[];
    /** 「新增属性」按钮副标(如 SKU「类目缺轴时用」);缺省仅「新增属性」。 */
    addHint?: string;
  }
>(function SpecEditor({ open, categoryCode, scope, initialSpec, addHint }, ref) {
  const { message } = App.useApp();
  const [rows, setRows] = useState<Row[]>([]);
  const [customSeq, setCustomSeq] = useState(0);

  useEffect(() => {
    if (!open) return;
    catalogApi
      .specSuggestions(categoryCode)
      .then((r) => setRows(buildRows(r.items, scope, initialSpec)))
      .catch(() => setRows(buildRows([], scope, initialSpec)));
    // initialSpec 随 open/编辑对象变化;categoryCode 决定模板。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, categoryCode, scope, initialSpec]);

  useImperativeHandle(ref, () => ({ collect: () => collectSpecItems(rows, message) }), [rows, message]);

  function updateTemplate(key: string, patch: Partial<TemplateRow>) {
    setRows((rs) => rs.map((r) => (r.fromTemplate && r.key === key ? { ...r, ...patch } : r)));
  }
  function updateCustom(localId: string, patch: Partial<CustomRow>) {
    setRows((rs) => rs.map((r) => (!r.fromTemplate && r.localId === localId ? { ...r, ...patch } : r)));
  }
  function addCustom() {
    setRows((rs) => [...rs, { fromTemplate: false, localId: `c${customSeq}`, labelZh: "", value: "" }]);
    setCustomSeq((n) => n + 1);
  }
  function removeCustom(localId: string) {
    setRows((rs) => rs.filter((r) => r.fromTemplate || r.localId !== localId));
  }

  const templateRows = rows.filter((r): r is TemplateRow => r.fromTemplate);
  const customRows = rows.filter((r): r is CustomRow => !r.fromTemplate);

  return (
    <>
      {templateRows.length === 0 && customRows.length === 0 && (
        <Text type="secondary">该类目暂无规格模板,可用下方「新增属性」手动补充。</Text>
      )}

      <Space orientation="vertical" size={10} style={{ width: "100%" }}>
        {templateRows.map((r) => (
          <div key={r.key} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 132, flex: "none", color: colors.muted, fontSize: 13 }}>
              {r.label}
              {r.unit ? <Text type="secondary"> [{r.unit}]</Text> : null}
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
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
        新增属性{addHint ? `(${addHint})` : ""}
      </Button>
    </>
  );
});
