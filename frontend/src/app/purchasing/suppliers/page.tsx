"use client";
import { useCallback, useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  Popconfirm,
  Row,
  Segmented,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";
import { Can } from "@/components/common/Can";
import { Permissions } from "@/config/permission-matrix";
import { useAuthStore } from "@/stores/authStore";
import {
  SUPPLIER_STATUS_META,
  supplierApi,
  type SupplierListItem,
  type SupplierOut,
  type SupplierSaveBody,
} from "@/lib/supplier";
import { colors } from "@/lib/tokens";

// 默认币种可选值(ISO4217,与报价/销售币种口径一致)。可空。
const CURRENCIES = ["USD", "CNY", "KES", "TZS", "EUR"];

const STATUS_TABS = [
  { label: "启用", value: "ACTIVE" },
  { label: "停用", value: "INACTIVE" },
  { label: "全部", value: "" },
];

type DrawerMode = "view" | "create" | "edit" | null;

export default function SupplierListPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const canManage = useAuthStore((s) => s.hasPermission(Permissions.SUPPLIER_MANAGE));

  const [rows, setRows] = useState<SupplierListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("ACTIVE");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const [mode, setMode] = useState<DrawerMode>(null);
  const [current, setCurrent] = useState<SupplierOut | null>(null);
  const [saving, setSaving] = useState(false);
  const [rowBusyId, setRowBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await supplierApi.list({
        status: status || undefined,
        q: q || undefined,
        page,
        size: 20,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      setLoadError(true);
      message.error(e instanceof Error ? e.message : "加载供应商列表失败");
    } finally {
      setLoading(false);
    }
  }, [status, q, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  async function openView(id: number) {
    setMode("view");
    setCurrent(null);
    try {
      setCurrent(await supplierApi.get(id));
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载供应商失败");
      setMode(null);
    }
  }

  async function openEdit(id: number) {
    try {
      const s = await supplierApi.get(id);
      setCurrent(s);
      form.setFieldsValue(s);
      setMode("edit");
    } catch (e) {
      message.error(e instanceof Error ? e.message : "加载供应商失败");
    }
  }

  function openCreate() {
    setCurrent(null);
    form.resetFields();
    setMode("create");
  }

  function closeDrawer() {
    setMode(null);
    setCurrent(null);
    form.resetFields();
  }

  async function onSubmit() {
    let values: SupplierSaveBody;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      if (mode === "create") {
        await supplierApi.create(values);
        message.success("已创建");
      } else if (mode === "edit" && current) {
        await supplierApi.update(current.id, values);
        message.success("已保存");
      }
      closeDrawer();
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(r: SupplierListItem) {
    setRowBusyId(r.id);
    try {
      if (r.status === "ACTIVE") {
        await supplierApi.deactivate(r.id);
        message.success("已停用");
      } else {
        await supplierApi.activate(r.id);
        message.success("已启用");
      }
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setRowBusyId(null);
    }
  }

  const columns: ColumnsType<SupplierListItem> = [
    { title: "编码", dataIndex: "code", width: 140 },
    { title: "名称", dataIndex: "name", ellipsis: true },
    { title: "默认币种", dataIndex: "default_currency", width: 100, render: (v) => v || "—" },
    { title: "联系人", dataIndex: "contact_name", width: 140, render: (v) => v || "—" },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (s: SupplierListItem["status"]) => {
        const m = SUPPLIER_STATUS_META[s];
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    ...(canManage
      ? [
          {
            title: "操作",
            key: "actions",
            width: 150,
            fixed: "right" as const,
            className: "whitespace-nowrap",
            render: (_: unknown, r: SupplierListItem) => (
              <Space size="small" onClick={(e) => e.stopPropagation()}>
                <Button type="link" size="small" onClick={() => openEdit(r.id)}>
                  编辑
                </Button>
                <Popconfirm
                  title={r.status === "ACTIVE" ? "停用该供应商?" : "启用该供应商?"}
                  description={
                    r.status === "ACTIVE"
                      ? "停用后不可被新采购单选用,历史单据不受影响。"
                      : "启用后可被采购单选用。"
                  }
                  onConfirm={() => toggleStatus(r)}
                >
                  <Button type="link" size="small" danger={r.status === "ACTIVE"} loading={rowBusyId === r.id}>
                    {r.status === "ACTIVE" ? "停用" : "启用"}
                  </Button>
                </Popconfirm>
              </Space>
            ),
          },
        ]
      : []),
  ];

  const readOnly = mode === "view";

  return (
    <Card>
      <Space style={{ marginBottom: 16, width: "100%", justifyContent: "space-between" }} wrap>
        <Space wrap>
          <Segmented
            options={STATUS_TABS}
            value={status}
            onChange={(v) => {
              setStatus(v as string);
              setPage(1);
            }}
          />
          <Input.Search
            placeholder="编码 / 名称 / 联系人"
            allowClear
            style={{ width: 240 }}
            onSearch={(v) => {
              setQ(v);
              setPage(1);
            }}
          />
        </Space>
        <Can perm={Permissions.SUPPLIER_MANAGE}>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建供应商
          </Button>
        </Can>
      </Space>

      {loadError && !rows.length ? (
        <div style={{ textAlign: "center", padding: "48px 0", color: colors.muted }}>
          加载失败
          <div style={{ marginTop: 12 }}>
            <Button onClick={load}>重试</Button>
          </div>
        </div>
      ) : (
        <Table<SupplierListItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 800 }}
          locale={{ emptyText: "暂无供应商" }}
          onRow={(r) => ({
            onClick: () => openView(r.id),
            style: { cursor: "pointer" },
          })}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            showSizeChanger: false,
            showTotal: (t) => `共 ${t} 条`,
            onChange: setPage,
          }}
        />
      )}

      <Drawer
        title={mode === "create" ? "新建供应商" : mode === "edit" ? "编辑供应商" : "供应商详情"}
        open={mode !== null}
        onClose={closeDrawer}
        width="min(560px, 92vw)"
        destroyOnClose
        extra={
          readOnly && canManage && current ? (
            <Button type="primary" onClick={() => openEdit(current.id)}>
              编辑
            </Button>
          ) : null
        }
        footer={
          readOnly ? null : (
            <Space style={{ width: "100%", justifyContent: "flex-end" }}>
              <Button onClick={closeDrawer} disabled={saving}>
                取消
              </Button>
              <Button type="primary" loading={saving} onClick={onSubmit}>
                保存
              </Button>
            </Space>
          )
        }
      >
        {readOnly ? (
          current ? (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="编码">{current.code}</Descriptions.Item>
              <Descriptions.Item label="名称">{current.name}</Descriptions.Item>
              <Descriptions.Item label="默认币种">{current.default_currency || "—"}</Descriptions.Item>
              <Descriptions.Item label="联系人">{current.contact_name || "—"}</Descriptions.Item>
              <Descriptions.Item label="电话">{current.contact_phone || "—"}</Descriptions.Item>
              <Descriptions.Item label="邮箱">{current.contact_email || "—"}</Descriptions.Item>
              <Descriptions.Item label="地址">{current.address || "—"}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag color={SUPPLIER_STATUS_META[current.status].color}>
                  {SUPPLIER_STATUS_META[current.status].label}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
          ) : null
        ) : (
          <Form form={form} layout="vertical">
            <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入供应商名称" }]}>
              <Input maxLength={120} placeholder="供应商名称" />
            </Form.Item>
            <Form.Item name="default_currency" label="默认币种">
              <Select
                allowClear
                placeholder="可空"
                options={CURRENCIES.map((c) => ({ value: c, label: c }))}
              />
            </Form.Item>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item name="contact_name" label="联系人">
                  <Input maxLength={60} placeholder="选填" />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item name="contact_phone" label="电话">
                  <Input maxLength={40} placeholder="选填" />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item name="contact_email" label="邮箱" rules={[{ type: "email", message: "邮箱格式不正确" }]}>
              <Input maxLength={120} placeholder="选填" />
            </Form.Item>
            <Form.Item name="address" label="地址" style={{ marginBottom: 0 }}>
              <Input.TextArea rows={2} maxLength={255} placeholder="选填" />
            </Form.Item>
          </Form>
        )}
      </Drawer>
    </Card>
  );
}
