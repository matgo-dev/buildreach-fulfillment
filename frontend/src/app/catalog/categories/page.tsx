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
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tree,
  Typography,
} from "antd";
import type { DataNode } from "antd/es/tree";
import type { ColumnsType } from "antd/es/table";
import { DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { useAuthStore } from "@/stores/authStore";
import {
  catalogApi,
  type CategoryNode,
  type CategorySpecAttribute,
  type SpecValueType,
  type SpecScope,
} from "@/lib/catalog";
import { display } from "@/lib/i18n";
import { colors } from "@/lib/tokens";
import { resolveBizError } from "@/lib/errorMessages";

type DrawerMode = "create" | "edit" | null;
type SpecDrawerMode = "create" | "edit" | null;

interface SpecFormValues {
  name_zh: string;
  name_en?: string;
  name_sw?: string;
  value_type: SpecValueType;
  unit?: string;
  sort_order: number;
  scope: SpecScope;
  options?: Array<{ code?: string; name_zh?: string; name_en?: string; name_sw?: string }>;
}

const CATEGORY_CODE_PATTERN = /^(?!00(?:\.|$))\d{2}(?:\.(?!000)\d{3}){0,2}$/;
const CATEGORY_CODE_MESSAGE = "编码格式应为 01 / 01.001 / 01.001.003";
const VALUE_TYPE_OPTIONS = [
  { label: "文本", value: "string" },
  { label: "数字", value: "number" },
  { label: "枚举", value: "enum" },
];
const SCOPE_OPTIONS = [
  { label: "产品级", value: "spu" },
  { label: "变体轴", value: "sku" },
];
const VALUE_TYPE_LABEL: Record<SpecValueType, string> = {
  string: "文本",
  number: "数字",
  enum: "枚举",
};
const SCOPE_LABEL: Record<SpecScope, string> = {
  spu: "产品级",
  sku: "变体轴",
};

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

function specPayload(v: SpecFormValues) {
  const valueType = v.value_type;
  const options =
    valueType === "enum"
      ? (v.options ?? [])
          .map((o) => ({
            code: o.code,
            label_i18n: namePayload({
              name_zh: o.name_zh ?? "",
              name_en: o.name_en,
              name_sw: o.name_sw,
            }),
          }))
      : null;
  return {
    label_i18n: namePayload(v),
    value_type: valueType,
    options,
    unit: v.unit?.trim() || null,
    sort_order: v.sort_order ?? 0,
    scope: v.scope,
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
  const [specForm] = Form.useForm();
  const canManage = useAuthStore((s) => s.hasPermission(Permissions.PRODUCT_MANAGE));
  const [nodes, setNodes] = useState<CategoryNode[]>([]);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [drawerMode, setDrawerMode] = useState<DrawerMode>(null);
  const [createParent, setCreateParent] = useState<CategoryNode | null>(null);
  const [specRows, setSpecRows] = useState<CategorySpecAttribute[]>([]);
  const [inheritedSpecRows, setInheritedSpecRows] = useState<CategorySpecAttribute[]>([]);
  const [specLoading, setSpecLoading] = useState(false);
  const [specSaving, setSpecSaving] = useState(false);
  const [specDrawerMode, setSpecDrawerMode] = useState<SpecDrawerMode>(null);
  const [specTarget, setSpecTarget] = useState<CategorySpecAttribute | null>(null);

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
  const specValueType = Form.useWatch("value_type", specForm);
  const treeData = useMemo(() => buildTree(nodes), [nodes]);
  const expandedKeys = useMemo(() => nodes.filter((n) => !n.is_leaf).map((n) => n.code), [nodes]);

  async function loadSpecs(code: string) {
    setSpecLoading(true);
    try {
      const [direct, suggestions] = await Promise.all([
        catalogApi.specAttributes(code),
        catalogApi.specSuggestions(code),
      ]);
      setSpecRows(direct.items);
      setInheritedSpecRows(
        suggestions.items.filter((item) => item.category_code && item.category_code !== code),
      );
    } catch (e) {
      message.error(resolveBizError(e, "加载规格模板失败"));
    } finally {
      setSpecLoading(false);
    }
  }

  useEffect(() => {
    if (!selectedCode) {
      setSpecRows([]);
      setInheritedSpecRows([]);
      return;
    }
    loadSpecs(selectedCode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCode]);

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

  function openCreateSpec() {
    if (!selected) return;
    setSpecTarget(null);
    specForm.resetFields();
    specForm.setFieldsValue({
      value_type: "string",
      scope: "sku",
      sort_order: (specRows.at(-1)?.sort_order ?? 0) + 10,
      options: [{ name_zh: "" }],
    });
    setSpecDrawerMode("create");
  }

  function openEditSpec(row: CategorySpecAttribute) {
    setSpecTarget(row);
    specForm.resetFields();
    specForm.setFieldsValue({
      name_zh: row.label_i18n.zh,
      name_en: row.label_i18n.en,
      name_sw: row.label_i18n.sw,
      value_type: row.value_type,
      unit: row.unit,
      sort_order: row.sort_order,
      scope: row.scope,
      options: (row.options ?? []).map((o) => ({
        code: o.code,
        name_zh: o.label_i18n.zh,
        name_en: o.label_i18n.en,
        name_sw: o.label_i18n.sw,
      })),
    });
    setSpecDrawerMode("edit");
  }

  function closeSpecDrawer() {
    setSpecDrawerMode(null);
    setSpecTarget(null);
    specForm.resetFields();
  }

  async function submitSpec() {
    if (!selected) return;
    let values: SpecFormValues;
    try {
      values = await specForm.validateFields();
    } catch {
      return;
    }
    setSpecSaving(true);
    try {
      if (specDrawerMode === "create") {
        await catalogApi.createSpecAttribute(selected.code, specPayload(values));
        message.success("已创建规格字段");
      } else if (specDrawerMode === "edit" && specTarget) {
        await catalogApi.updateSpecAttribute(selected.code, specTarget.key, specPayload(values));
        message.success("已保存规格字段");
      }
      closeSpecDrawer();
      await loadSpecs(selected.code);
    } catch (e) {
      message.error(resolveBizError(e, "保存规格字段失败"));
    } finally {
      setSpecSaving(false);
    }
  }

  async function deleteSpec(row: CategorySpecAttribute) {
    if (!selected) return;
    try {
      await catalogApi.deleteSpecAttribute(selected.code, row.key);
      message.success("已删除规格字段");
      await loadSpecs(selected.code);
    } catch (e) {
      message.error(resolveBizError(e, "删除规格字段失败"));
    }
  }

  const specColumns: ColumnsType<CategorySpecAttribute> = [
    {
      title: "字段",
      dataIndex: "label_i18n",
      render: (_, row) => (
        <Space size={6}>
          <span>{display(row.label_i18n) || row.key}</span>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {row.key}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: "类型",
      dataIndex: "value_type",
      width: 80,
      render: (v: SpecValueType) => VALUE_TYPE_LABEL[v] ?? v,
    },
    {
      title: "归属",
      dataIndex: "scope",
      width: 90,
      render: (v: SpecScope) => <Tag color={v === "spu" ? "blue" : "green"}>{SCOPE_LABEL[v]}</Tag>,
    },
    { title: "单位", dataIndex: "unit", width: 90, render: (v) => v || "—" },
    {
      title: "选项",
      dataIndex: "options",
      ellipsis: true,
      render: (options: CategorySpecAttribute["options"]) =>
        options?.length ? options.map((o) => display(o.label_i18n) || o.code).join(" / ") : "—",
    },
    { title: "排序", dataIndex: "sort_order", width: 80 },
    {
      title: "操作",
      key: "actions",
      width: 110,
      fixed: "right" as const,
      render: (_, row) =>
        canManage ? (
          <Space size="small">
            <Button type="link" size="small" onClick={() => openEditSpec(row)}>
              编辑
            </Button>
            <Popconfirm title="删除该规格字段?" onConfirm={() => deleteSpec(row)}>
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          </Space>
        ) : null,
    },
  ];

  const inheritedColumns: ColumnsType<CategorySpecAttribute> = [
    ...specColumns.filter((col) => col.key !== "actions"),
    {
      title: "来源",
      dataIndex: "category_code",
      width: 100,
      render: (v) => v,
    },
  ];

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
            <>
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

              <div style={{ marginTop: 20 }}>
                <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 8 }}>
                  <Typography.Title level={5} style={{ margin: 0 }}>
                    直属规格模板
                  </Typography.Title>
                  {canManage && (
                    <Button size="small" icon={<PlusOutlined />} onClick={openCreateSpec}>
                      新建字段
                    </Button>
                  )}
                </Space>
                <Table<CategorySpecAttribute>
                  rowKey="key"
                  size="small"
                  columns={specColumns}
                  dataSource={specRows}
                  loading={specLoading}
                  pagination={false}
                  scroll={{ x: 880 }}
                  locale={{ emptyText: "暂无直属规格字段" }}
                />
              </div>

              <div style={{ marginTop: 20 }}>
                <Typography.Title level={5} style={{ marginTop: 0, marginBottom: 8 }}>
                  继承规格模板
                </Typography.Title>
                <Table<CategorySpecAttribute>
                  rowKey={(row) => `${row.category_code}:${row.key}`}
                  size="small"
                  columns={inheritedColumns}
                  dataSource={inheritedSpecRows}
                  loading={specLoading}
                  pagination={false}
                  scroll={{ x: 880 }}
                  locale={{ emptyText: "暂无继承规格字段" }}
                />
              </div>
            </>
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

      <Drawer
        title={specDrawerMode === "create" ? "新建规格字段" : "编辑规格字段"}
        open={specDrawerMode !== null}
        onClose={closeSpecDrawer}
        width="min(620px, 94vw)"
        destroyOnClose
        footer={
          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button onClick={closeSpecDrawer} disabled={specSaving}>
              取消
            </Button>
            <Button type="primary" loading={specSaving} onClick={submitSpec}>
              保存
            </Button>
          </Space>
        }
      >
        <Form form={specForm} layout="vertical">
          {specDrawerMode === "edit" && (
            <Form.Item label="字段 Key">
              <Input value={specTarget?.key} disabled />
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
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item
                label="字段类型"
                name="value_type"
                rules={[{ required: true, message: "请选择字段类型" }]}
              >
                <Select options={VALUE_TYPE_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="归属层"
                name="scope"
                rules={[{ required: true, message: "请选择归属层" }]}
              >
                <Select options={SCOPE_OPTIONS} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label="单位" name="unit">
                <Input maxLength={20} placeholder="如 mm / kg / m2" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                label="排序"
                name="sort_order"
                rules={[{ required: true, message: "请输入排序" }]}
              >
                <InputNumber min={0} precision={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
          </Row>

          {specValueType === "enum" && (
            <Form.List name="options">
              {(fields, { add, remove }) => (
                <div>
                  <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 8 }}>
                    <Typography.Text strong>枚举选项</Typography.Text>
                    <Button size="small" icon={<PlusOutlined />} onClick={() => add({ name_zh: "" })}>
                      添加选项
                    </Button>
                  </Space>
                  {fields.map((field) => (
                    <Row key={field.key} gutter={8} align="middle">
                      <Form.Item name={[field.name, "code"]} hidden>
                        <Input />
                      </Form.Item>
                      <Col span={7}>
                        <Form.Item
                          {...field}
                          name={[field.name, "name_zh"]}
                          rules={[{ required: true, message: "中文名必填" }]}
                        >
                          <Input placeholder="中文名" maxLength={100} />
                        </Form.Item>
                      </Col>
                      <Col span={7}>
                        <Form.Item {...field} name={[field.name, "name_en"]}>
                          <Input placeholder="英文名" maxLength={100} />
                        </Form.Item>
                      </Col>
                      <Col span={7}>
                        <Form.Item {...field} name={[field.name, "name_sw"]}>
                          <Input placeholder="斯语名" maxLength={100} />
                        </Form.Item>
                      </Col>
                      <Col span={3}>
                        <Button
                          aria-label="删除选项"
                          icon={<DeleteOutlined />}
                          onClick={() => remove(field.name)}
                        />
                      </Col>
                    </Row>
                  ))}
                </div>
              )}
            </Form.List>
          )}
        </Form>
      </Drawer>
    </Row>
  );
}
