"use client";
import { useEffect, useState } from "react";
import { Drawer, Form, Input, TreeSelect, Button, Space, App } from "antd";
import { catalogApi, CategoryNode, SpuOut } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { ImageUpload } from "@/components/common/ImageUpload";

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
  spu?: SpuOut;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const [cats, setCats] = useState<CatTreeNode[]>([]);
  const [mainImage, setMainImage] = useState<string | null>(null);
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
    setMainImage(spu?.main_image ?? null);
  }, [open, spu, form]);

  async function onSubmit() {
    const v = await form.validateFields();
    if (!mainImage) {
      message.error("主图必填");
      return;
    }
    setSaving(true);
    try {
      const body = {
        category_code: v.category_code,
        name_i18n: { zh: v.name_zh.trim() },
        main_image: mainImage,
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
      width={460}
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
          <Input placeholder="如:镀锌钢管" maxLength={120} />
        </Form.Item>
        <Form.Item label="主图(必填)" required>
          <ImageUpload value={mainImage} onChange={setMainImage} />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
