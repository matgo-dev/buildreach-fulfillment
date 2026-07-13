"use client";
import { useEffect, useRef, useState } from "react";
import { Drawer, Form, Input, TreeSelect, Button, Space, Divider, App } from "antd";
import { catalogApi, CategoryNode, ImageRefIn, SpuDetail } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { SpuImageManager } from "@/components/catalog/ImageManager";
import { SpecEditor, SpecEditorHandle } from "@/components/catalog/SpecEditor";
import { colors } from "@/lib/tokens";

interface CatTreeNode {
  value: string;
  title: string;
  selectable: boolean;
  children?: CatTreeNode[];
}

// 分类树 → TreeSelect:非叶子 selectable=false(仅叶子可作归属,Addendum C)。
function buildTreeSelect(nodes: CategoryNode[]): CatTreeNode[] {
  const byParent = new Map<string | null, CategoryNode[]>();
  nodes.forEach((n) => {
    const arr = byParent.get(n.parent_code) ?? [];
    arr.push(n);
    byParent.set(n.parent_code, arr);
  });
  const make = (parent: string | null): CatTreeNode[] =>
    (byParent.get(parent) ?? []).map((n) => ({
      value: n.code,
      title: display(n.name_i18n) || n.code,
      selectable: n.is_leaf,
      children: n.is_leaf ? undefined : make(n.code),
    }));
  return make(null);
}

// 点分 code 的完整链(各级前缀含自身):"20.003.004" → ["20","20.003","20.003.004"]。
// 预展开表单分类树到携带的分类,方便从父节点继续下钻到叶子。
function catChain(code: string): string[] {
  const parts = code.split(".");
  return parts.map((_, i) => parts.slice(0, i + 1).join("."));
}

export function SpuForm({
  open,
  spu,
  defaultCategoryCode,
  defaultCategoryIsLeaf,
  onClose,
  onSaved,
}: {
  open: boolean;
  spu?: SpuDetail;
  /** 新建时列表左树选中的分类(来自 ?category=)。编辑时忽略,以 spu 自身分类为准。 */
  defaultCategoryCode?: string;
  /** 上面那个分类是否叶子:叶子→直接预填为值;父节点→只把表单树预展开到它,引导继续下钻到叶子。 */
  defaultCategoryIsLeaf?: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [cats, setCats] = useState<CatTreeNode[]>([]);
  const [catCode, setCatCode] = useState<string | undefined>(undefined);
  const [treeExpanded, setTreeExpanded] = useState<string[]>([]);
  const [images, setImages] = useState<ImageRefIn[]>([]);
  const [saving, setSaving] = useState(false);
  const specRef = useRef<SpecEditorHandle>(null);

  useEffect(() => {
    if (open) catalogApi.categoriesTree().then((r) => setCats(buildTreeSelect(r.items)));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    // 携带的分类:叶子→作为值预填(TreeSelect 只接受叶子);父节点→不填值,仅预展开引导下钻。
    const carried = spu?.category_code ?? defaultCategoryCode;
    const preValue = spu?.category_code ?? (defaultCategoryIsLeaf ? defaultCategoryCode : undefined);
    setCatCode(preValue);
    setTreeExpanded(carried ? catChain(carried) : []);
    form.setFieldsValue(
      spu
        ? {
            category_code: spu.category_code,
            name_zh: display(spu.name_i18n),
            brand: spu.brand ?? "",
            hs_code: spu.hs_code ?? "",
            description: spu.description ?? "",
          }
        : { category_code: preValue, name_zh: "", brand: "", hs_code: "", description: "" },
    );
    setImages(
      spu
        ? spu.images.map((i) => ({
            image_key: i.image_key,
            image_type: i.image_type,
            sort_order: i.sort_order,
          }))
        : [],
    );
  }, [open, spu, defaultCategoryCode, defaultCategoryIsLeaf, form]);

  async function onSubmit() {
    const v = await form.validateFields();
    if (!images.some((i) => i.image_type === "MAIN")) {
      message.error("请至少上传一张主图(封面)");
      return;
    }
    const spec_items = specRef.current?.collect();
    if (spec_items === null) return; // 手输行缺标签 → 阻断(collect 返回 null)
    setSaving(true);
    try {
      const body = {
        category_code: v.category_code,
        name_i18n: { zh: v.name_zh.trim() },
        brand: v.brand?.trim() || null,
        hs_code: v.hs_code?.trim() || null,
        description: v.description?.trim() || null,
        spec_items: spec_items ?? [],
        images,
      };
      if (spu) await catalogApi.updateSpu(spu.id, body);
      else await catalogApi.createSpu(body);
      message.success("已保存");
      onSaved();
      onClose();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      title={spu ? "编辑 SPU" : "新建 SPU"}
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
          name="category_code"
          label="分类(仅叶子可选)"
          rules={[{ required: true, message: "请选择分类" }]}
        >
          <TreeSelect
            treeData={cats}
            showSearch
            treeNodeFilterProp="title"
            placeholder="选择分类"
            allowClear
            style={{ maxWidth: 360 }}
            treeExpandedKeys={treeExpanded}
            onTreeExpand={(keys) => setTreeExpanded(keys as string[])}
            onChange={(v) => setCatCode(v)}
          />
        </Form.Item>
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
          <Input placeholder="如:镀锌钢管" maxLength={120} style={{ maxWidth: 360 }} />
        </Form.Item>
        <Form.Item name="brand" label="品牌(选填)">
          <Input placeholder="如:海螺" maxLength={100} style={{ maxWidth: 360 }} />
        </Form.Item>
        <Form.Item name="hs_code" label="HS 编码(选填)">
          <Input placeholder="海关归类码,如 2523290000" maxLength={20} style={{ maxWidth: 360 }} />
        </Form.Item>
        <Form.Item name="description" label="描述(选填)">
          <Input.TextArea
            placeholder="商品说明(非内部备注)"
            rows={3}
            maxLength={1000}
            showCount
            style={{ maxWidth: 480 }}
          />
        </Form.Item>
      </Form>

      <Divider titlePlacement="left" plain style={{ marginTop: 8 }}>
        产品级规格(整个商品一致,如材质/执行标准;区分变体的规格放 SKU)
      </Divider>
      {catCode ? (
        <SpecEditor
          ref={specRef}
          open={open}
          categoryCode={catCode}
          scope="spu"
          initialSpec={spu?.spec_jsonb}
        />
      ) : (
        <div style={{ fontSize: 13, color: colors.muted }}>先选分类,再维护产品级规格。</div>
      )}

      <Divider titlePlacement="left" plain style={{ marginTop: 16 }}>
        图片
      </Divider>
      <SpuImageManager value={images} onChange={setImages} />
    </Drawer>
  );
}
