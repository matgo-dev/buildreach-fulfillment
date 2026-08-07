"use client";
import { useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Row,
  Space,
  Spin,
  Tag,
  Tree,
  Typography,
} from "antd";
import type { DataNode } from "antd/es/tree";
import { EditOutlined, PlusOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { useAuthStore } from "@/stores/authStore";
import { catalogApi, type CategoryNode } from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { colors } from "@/lib/tokens";
import { resolveBizError } from "@/lib/errorMessages";

type DrawerMode = "create" | "edit" | null;

const CATEGORY_CODE_PATTERN = /^(?!00(?:\.|$))\d{2}(?:\.(?!000)\d{3}){0,2}$/;
const CATEGORY_CODE_MESSAGE = "编码格式应为 01 / 01.001 / 01.001.003";

function buildTree(nodes: CategoryNode[]): DataNode[] {
  const byParent = new Map<string | null, CategoryNode[]>();
  nodes.forEach((n) => {
    const arr = byParent.get(n.parent_code) ?? [];
    arr.push(n);
    byParent.set(n.parent_code, arr);
  });
  const make = (parent: string | null): DataNode[] =>
    (byParent.get(parent) ?? []).map((n) => ({
      key: n.code,
      title: (
        <Space size={6}>
          <span style={{ color: n.is_active ? undefined : colors.muted }}>
            {display(n.name_i18n) || n.code}
          </span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {n.code}
          </Typography.Text>
          {!n.is_active && <Tag>停用</Tag>}
        </Space>
      ),
      isLeaf: n.is_leaf,
      children: make(n.code),
    }));
  return make(null);
}

function namePayload(v: { name_zh: string; name_en?: string; name_sw?: string }) {
  return {
    zh: v.name_zh.trim(),
    ...(v.name_en?.trim() ? { en: v.name_en.trim() } : {}),
    ...(v.name_sw?.trim() ? { sw: v.name_sw.trim() } : {}),
  };
}

function validateCategoryCode(code: string, parent: CategoryNode | null): string | null {
  if (!CATEGORY_CODE_PATTERN.test(code)) return CATEGORY_CODE_MESSAGE;
  const level = code.split(".").length;
  if (!parent) {
    return level === 1 ? null : "根分类编码必须是一段,例如 01";
  }
  const parentLevel = parent.code.split(".").length;
  if (parentLevel >= 3) return "分类最多支持三级";
  if (level !== parentLevel + 1 || !code.startsWith(`${parent.code}.`)) {
    return "子分类编码必须在父级编码后追加一段三位数字";
  }
  return null;
}

export default function CategoryAdminPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const canManage = useAuthStore((s) => s.hasPermission(Permissions.PRODUCT_MANAGE));
  const [nodes, setNodes] = useState<CategoryNode[]>([]);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>(null);
  const [createParent, setCreateParent] = useState<CategoryNode | null>(null);

  async function load() {
    setLoading(true);
    try {
      const r = await catalogApi.categoriesTree({ include_inactive: true });
      setNodes(r.items);
      if (selectedCode && !r.items.some((n) => n.code === selectedCode)) {
        setSelectedCode(null);
      }
    } catch (e) {
      message.error(resolveBizError(e, "加载分类失败"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = useMemo(
    () => nodes.find((n) => n.code === selectedCode) ?? null,
    [nodes, selectedCode],
  );
  const treeData = useMemo(() => buildTree(nodes), [nodes]);
  const expandedKeys = useMemo(() => nodes.filter((n) => !n.is_leaf).map((n) => n.code), [nodes]);

  function openCreate(parent: CategoryNode | null) {
    setCreateParent(parent);
    form.resetFields();
    form.setFieldsValue({
      parent_code: parent?.code ?? null,
      parent_name: parent ? display(parent.name_i18n) : "根分类",
      sort_order: 0,
    });
    setDrawerMode("create");
  }

  function openEdit(cat: CategoryNode) {
    setCreateParent(null);
    form.resetFields();
    form.setFieldsValue({
      code: cat.code,
      name_zh: cat.name_i18n.zh,
      name_en: cat.name_i18n.en,
      name_sw: cat.name_i18n.sw,
      sort_order: cat.sort_order,
    });
    setDrawerMode("edit");
  }

  function closeDrawer() {
    setDrawerMode(null);
    setCreateParent(null);
    form.resetFields();
  }

  async function submit() {
    let values: {
      code?: string;
      parent_code?: string | null;
      name_zh: string;
      name_en?: string;
      name_sw?: string;
      sort_order: number;
    };
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      if (drawerMode === "create") {
        const created = await catalogApi.createCategory({
          code: values.code?.trim(),
          parent_code: createParent?.code ?? null,
          name_i18n: namePayload(values),
          sort_order: values.sort_order ?? 0,
        });
        setSelectedCode(created.code);
        message.success("已创建");
      } else if (drawerMode === "edit" && selected) {
        await catalogApi.updateCategory(selected.code, {
          name_i18n: namePayload(values),
          sort_order: values.sort_order ?? 0,
        });
        message.success("已保存");
      }
      closeDrawer();
      await load();
    } catch (e) {
      message.error(resolveBizError(e, "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  async function setActive(active: boolean) {
    if (!selected) return;
    try {
      if (active) {
        await catalogApi.activateCategory(selected.code);
        message.success("已启用");
      } else {
        await catalogApi.deactivateCategory(selected.code);
        message.success("已停用");
      }
      await load();
    } catch (e) {
      message.error(resolveBizError(e, "操作失败"));
    }
  }

  return (
    <Row gutter={16} wrap={false} style={{ height: "100%" }}>
      <Col flex="320px">
        <Card
          size="small"
          title="分类树"
          extra={
            <Can perm={Permissions.PRODUCT_MANAGE}>
              <Button size="small" icon={<PlusOutlined />} onClick={() => openCreate(null)}>
                新建根分类
              </Button>
            </Can>
          }
          style={{ height: "100%", display: "flex", flexDirection: "column" }}
          styles={{ body: { flex: "1 1 auto", minHeight: 0, overflowY: "auto" } }}
        >
          {loading ? (
            <Spin style={{ padding: 16 }} />
          ) : (
            <Tree
              showLine
              blockNode
              defaultExpandedKeys={expandedKeys}
              selectedKeys={selectedCode ? [selectedCode] : []}
              treeData={treeData}
              onSelect={(keys) => setSelectedCode((keys[0] as string | undefined) ?? null)}
            />
          )}
        </Card>
      </Col>
      <Col flex="auto" style={{ minWidth: 0 }}>
        <Card
          size="small"
          title={selected ? display(selected.name_i18n) || selected.code : "分类详情"}
          style={{ height: "100%" }}
          extra={
            selected && canManage ? (
              <Space>
                <Button
                  icon={<PlusOutlined />}
                  onClick={() => openCreate(selected)}
                  disabled={selected.level >= 3}
                >
                  新建子类
                </Button>
                <Button icon={<EditOutlined />} onClick={() => openEdit(selected)}>
                  编辑
                </Button>
                {selected.is_active ? (
                  <Popconfirm
                    title="停用该分类?"
                    description="停用会同时隐藏它下面的子分类。历史商品仍保留原分类。"
                    onConfirm={() => setActive(false)}
                  >
                    <Button danger>停用</Button>
                  </Popconfirm>
                ) : (
                  <Button onClick={() => setActive(true)}>启用</Button>
                )}
              </Space>
            ) : null
          }
        >
          {selected ? (
            <Descriptions column={1} bordered size="small">
              <Descriptions.Item label="编码">{selected.code}</Descriptions.Item>
              <Descriptions.Item label="父级">{selected.parent_code || "根分类"}</Descriptions.Item>
              <Descriptions.Item label="层级">{selected.level}</Descriptions.Item>
              <Descriptions.Item label="叶子">{selected.is_leaf ? "是" : "否"}</Descriptions.Item>
              <Descriptions.Item label="排序">{selected.sort_order}</Descriptions.Item>
              <Descriptions.Item label="状态">
                {selected.is_active ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>}
              </Descriptions.Item>
              <Descriptions.Item label="中文名">{selected.name_i18n.zh || "—"}</Descriptions.Item>
              <Descriptions.Item label="英文名">{selected.name_i18n.en || "—"}</Descriptions.Item>
              <Descriptions.Item label="斯语名">{selected.name_i18n.sw || "—"}</Descriptions.Item>
            </Descriptions>
          ) : (
            <Typography.Text type="secondary">请选择左侧分类</Typography.Text>
          )}
        </Card>
      </Col>

      <Drawer
        title={drawerMode === "create" ? "新建分类" : "编辑分类"}
        open={drawerMode !== null}
        onClose={closeDrawer}
        width="min(560px, 92vw)"
        destroyOnClose
        footer={
          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button onClick={closeDrawer} disabled={saving}>
              取消
            </Button>
            <Button type="primary" loading={saving} onClick={submit}>
              保存
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical">
          {drawerMode === "create" ? (
            <>
              <Form.Item label="父级" name="parent_name">
                <Input disabled />
              </Form.Item>
              <Form.Item
                label="编码"
                name="code"
                normalize={(v) => (typeof v === "string" ? v.trim() : v)}
                rules={[
                  { required: true, message: "请输入分类编码" },
                  {
                    validator: (_, value) => {
                      const code = typeof value === "string" ? value.trim() : "";
                      if (!code) return Promise.resolve();
                      const error = validateCategoryCode(code, createParent);
                      return error ? Promise.reject(new Error(error)) : Promise.resolve();
                    },
                  },
                ]}
              >
                <Input maxLength={10} placeholder={createParent ? `${createParent.code}.001` : "如 08"} />
              </Form.Item>
            </>
          ) : (
            <Form.Item label="编码" name="code">
              <Input disabled />
            </Form.Item>
          )}
          <Form.Item
            label="中文名"
            name="name_zh"
            rules={[{ required: true, message: "请输入中文名" }]}
          >
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item label="英文名" name="name_en">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item label="斯语名" name="name_sw">
            <Input maxLength={100} />
          </Form.Item>
          <Form.Item label="排序" name="sort_order" rules={[{ required: true, message: "请输入排序" }]}>
            <InputNumber min={0} precision={0} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Drawer>
    </Row>
  );
}
