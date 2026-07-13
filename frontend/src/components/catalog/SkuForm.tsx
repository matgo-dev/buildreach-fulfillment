"use client";
import { useEffect, useMemo, useRef, useState } from "react";
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
import {
  catalogApi,
  SkuWithImages,
  SpecDisplayItem,
  UnitOut,
  specDisplayText,
} from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { ImageZone } from "@/components/catalog/ImageManager";
import { SpecEditor, SpecEditorHandle } from "@/components/catalog/SpecEditor";
import { colors } from "@/lib/tokens";

const { Text } = Typography;

export function SkuForm({
  open,
  spuId,
  categoryCode,
  spuSpec,
  sku,
  copyFrom,
  onClose,
  onSaved,
}: {
  open: boolean;
  spuId: number;
  categoryCode: string;
  /** 父 SPU 产品级规格(只读回显,让运营知道继承上下文);来自详情 spu.spec_display。 */
  spuSpec?: SpecDisplayItem[];
  sku?: SkuWithImages;
  copyFrom?: SkuWithImages;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [units, setUnits] = useState<UnitOut[]>([]);
  const [imageKeys, setImageKeys] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const specRef = useRef<SpecEditorHandle>(null);

  const source = sku ?? copyFrom;

  useEffect(() => {
    if (!open) return;
    catalogApi.units().then((r) => setUnits(r.items)).catch(() => setUnits([]));
    form.setFieldsValue(
      source
        ? {
            name_zh: display(source.name_i18n) + (copyFrom && !sku ? " 副本" : ""),
            unit: source.unit,
            reference_price: source.reference_price ?? undefined,
            weight_kg: source.weight_kg ?? undefined,
            length_cm: source.length_cm ?? undefined,
            width_cm: source.width_cm ?? undefined,
            height_cm: source.height_cm ?? undefined,
          }
        : { name_zh: "", unit: undefined, reference_price: undefined,
            weight_kg: undefined, length_cm: undefined, width_cm: undefined, height_cm: undefined },
    );
    setImageKeys(sku ? sku.images.map((i) => i.image_key) : []); // 复制不带图片
  }, [open, sku, copyFrom, form, source]);

  async function onSubmit() {
    const v = await form.validateFields();
    const spec_items = specRef.current?.collect();
    if (spec_items == null) return; // 手输行缺标签 → 阻断
    setSaving(true);
    try {
      const body = {
        spu_id: spuId,
        unit: v.unit,
        name_i18n: { zh: v.name_zh.trim() },
        reference_price: v.reference_price ?? null,
        weight_kg: v.weight_kg ?? null,
        length_cm: v.length_cm ?? null,
        width_cm: v.width_cm ?? null,
        height_cm: v.height_cm ?? null,
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

  // 只回显 SPU 产品级(scope=spu)项——spu.spec_display 已仅含产品级,稳妥再过滤一次。
  const productSpec = (spuSpec ?? []).filter((s) => s.scope === "spu");

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={680}
      title={sku ? "编辑 SKU" : copyFrom ? "复制 SKU" : "新建 SKU"}
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
        <Form.Item label="重量(kg,选填)" name="weight_kg">
          <InputNumber style={{ width: 200 }} min={0} precision={3} addonAfter="kg" placeholder="单个售卖单位净重" />
        </Form.Item>
        <Space size={12} wrap>
          <Form.Item label="长(cm)" name="length_cm">
            <InputNumber style={{ width: 130 }} min={0} precision={2} addonAfter="cm" />
          </Form.Item>
          <Form.Item label="宽(cm)" name="width_cm">
            <InputNumber style={{ width: 130 }} min={0} precision={2} addonAfter="cm" />
          </Form.Item>
          <Form.Item label="高(cm)" name="height_cm">
            <InputNumber style={{ width: 130 }} min={0} precision={2} addonAfter="cm" />
          </Form.Item>
        </Space>
      </Form>

      <Divider titlePlacement="left" plain style={{ marginTop: 8 }}>
        SKU 图(可选)
      </Divider>
      <div style={{ marginBottom: 4, fontSize: 12, color: colors.muted }}>
        该 SKU 有专属图时上传,否则自动用商品主图。
      </div>
      <ImageZone title="SKU 图" keys={imageKeys} max={6} onChange={setImageKeys} />

      {/* 产品级规格在 SPU 上维护,这里只读回显,避免运营误以为要重填。 */}
      <Divider titlePlacement="left" plain style={{ marginTop: 8 }}>
        产品级规格(继承自 SPU,只读)
      </Divider>
      <div style={{ fontSize: 13, color: colors.muted }}>
        {productSpec.length ? specDisplayText(productSpec) : "该 SPU 暂无产品级规格,可在 SPU 编辑页补充。"}
      </div>

      <Divider titlePlacement="left" plain style={{ marginTop: 8 }}>
        变体规格(本 SKU 独有,按类目模板铺开,留空不提交)
      </Divider>
      <SpecEditor
        ref={specRef}
        open={open}
        categoryCode={categoryCode}
        scope="sku"
        initialSpec={source?.spec_jsonb}
        addHint="类目缺轴时用"
      />
      <div style={{ marginTop: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          变体规格用于区分同一商品下的不同 SKU(如管径、壁厚)。
        </Text>
      </div>
    </Drawer>
  );
}
