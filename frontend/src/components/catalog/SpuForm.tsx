"use client";
import { useEffect, useState } from "react";
import { Drawer, Form, Input, TreeSelect, Button, Space, App } from "antd";
import { catalogApi, CategoryNode, ImageRefIn, SpuDetail } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { SpuImageManager } from "@/components/catalog/ImageManager";

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

export function SpuForm({
  open,
  spu,
  onClose,
  onSaved,
}: {
  open: boolean;
  spu?: SpuDetail;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [cats, setCats] = useState<CatTreeNode[]>([]);
  const [images, setImages] = useState<ImageRefIn[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) catalogApi.categoriesTree().then((r) => setCats(buildTreeSelect(r.items)));
  }, [open]);

  useEffect(() => {
    if (!open) return;
    form.setFieldsValue(
      spu
        ? { category_code: spu.category_code, name_zh: display(spu.name_i18n) }
        : { category_code: undefined, name_zh: "" },
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
  }, [open, spu, form]);

  async function onSubmit() {
    const v = await form.validateFields();
    if (!images.some((i) => i.image_type === "MAIN")) {
      message.error("请至少上传一张主图(封面)");
      return;
    }
    setSaving(true);
    try {
      const body = {
        category_code: v.category_code,
        name_i18n: { zh: v.name_zh.trim() },
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
            treeDefaultExpandAll
            placeholder="选择分类"
            allowClear
            style={{ maxWidth: 360 }}
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
      </Form>
      <SpuImageManager value={images} onChange={setImages} />
    </Drawer>
  );
}
