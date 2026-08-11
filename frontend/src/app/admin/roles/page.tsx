"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { CheckOutlined, DeleteOutlined, EditOutlined, PlusOutlined } from "@ant-design/icons";
import { PageLoading } from "@/components/common/PageLoading";
import { ListErrorState } from "@/components/common/ListErrorState";
import { resolveBizError } from "@/lib/errorMessages";
import { roleApi, type RoleOut, type RolePermissionItem } from "@/lib/role";
import { colors } from "@/lib/tokens";

const MODULE_ORDER = ["auth", "system", "fulfillment"] as const;
const MODULE_LABEL: Record<string, string> = {
  auth: "会话",
  system: "系统",
  fulfillment: "履约业务",
};

interface PermissionRow {
  code: string;
  name: string;
  module: string;
  byRole: Record<string, boolean>;
}

interface RoleFormValues {
  code?: string;
  name: string;
  description?: string;
  permissions: string[];
}

export default function RolePermissionMatrixPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm<RoleFormValues>();
  const [roles, setRoles] = useState<RoleOut[]>([]);
  const [assignable, setAssignable] = useState<RolePermissionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [editing, setEditing] = useState<RoleOut | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [roleRows, permRows] = await Promise.all([
        roleApi.list(),
        roleApi.assignablePermissions(),
      ]);
      setRoles(roleRows);
      setAssignable(permRows);
    } catch (e) {
      setLoadError(true);
      message.error(resolveBizError(e, "加载角色权限失败"));
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    load();
  }, [load]);

  const customRoles = useMemo(
    () => roles.filter((r) => !r.is_system && r.is_custom_readonly),
    [roles],
  );
  const assignableOptions = useMemo(
    () => assignable.map((p) => ({
      value: p.code,
      label: `${p.name} (${p.code})`,
    })),
    [assignable],
  );

  function openCreate() {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ permissions: [] });
    setModalOpen(true);
  }

  function openEdit(role: RoleOut) {
    setEditing(role);
    form.setFieldsValue({
      name: role.name,
      description: role.description ?? undefined,
      permissions: role.permissions
        .map((p) => p.code)
        .filter((code) => assignable.some((p) => p.code === code)),
    });
    setModalOpen(true);
  }

  async function submitRole() {
    const values = await form.validateFields().catch(() => null);
    if (!values) return;
    setSaving(true);
    try {
      if (editing) {
        await roleApi.update(editing.code, {
          name: values.name,
          description: values.description ?? null,
          permissions: values.permissions,
        });
        message.success("角色已更新");
      } else {
        await roleApi.create({
          code: values.code,
          name: values.name,
          description: values.description ?? null,
          permissions: values.permissions,
        });
        message.success("角色已创建");
      }
      setModalOpen(false);
      await load();
    } catch (e) {
      message.error(resolveBizError(e, "保存角色失败"));
    } finally {
      setSaving(false);
    }
  }

  async function deleteRole(role: RoleOut) {
    try {
      await roleApi.delete(role.code);
      message.success("角色已删除");
      await load();
    } catch (e) {
      message.error(resolveBizError(e, "删除角色失败"));
    }
  }

  if (loading && !roles.length) return <PageLoading />;
  if (loadError && !roles.length) return <ListErrorState onRetry={load} />;

  const permIndex = new Map<string, PermissionRow>();
  roles.forEach((role) => {
    role.permissions.forEach((p) => {
      const row = permIndex.get(p.code) ?? { code: p.code, name: p.name, module: p.module, byRole: {} };
      row.byRole[role.code] = true;
      permIndex.set(p.code, row);
    });
  });

  const customColumns: ColumnsType<RoleOut> = [
    {
      title: "角色",
      dataIndex: "name",
      width: 180,
      render: (name: string, r) => (
        <span>
          {name}
          <span style={{ color: colors.muted, marginLeft: 8, fontSize: 12 }}>{r.code}</span>
        </span>
      ),
    },
    {
      title: "权限",
      dataIndex: "permissions",
      render: (perms: RolePermissionItem[]) => (
        <Space size={[4, 4]} wrap>
          {perms
            .filter((p) => p.module !== "auth")
            .map((p) => <Tag key={p.code}>{p.name}</Tag>)}
        </Space>
      ),
    },
    {
      title: "说明",
      dataIndex: "description",
      width: 220,
      ellipsis: true,
      render: (v) => v || "—",
    },
    {
      title: "操作",
      key: "actions",
      width: 130,
      align: "right",
      render: (_: unknown, r) => (
        <Space size="small">
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(r)} />
          <Popconfirm
            title="删除该角色?"
            description="已分配给用户的角色不能删除。"
            okButtonProps={{ danger: true }}
            onConfirm={() => deleteRole(r)}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const permColumn: ColumnsType<PermissionRow>[number] = {
    title: "权限点",
    dataIndex: "name",
    width: 220,
    render: (name: string, r: PermissionRow) => (
      <span>
        {name}
        <span style={{ color: colors.muted, marginLeft: 8, fontSize: 12 }}>{r.code}</span>
      </span>
    ),
  };
  const roleColumn = (role: RoleOut): ColumnsType<PermissionRow>[number] => ({
    title: (
      <span>
        {role.name}
        <span style={{ color: colors.muted, marginLeft: 6, fontSize: 12 }}>{role.code}</span>
      </span>
    ),
    key: role.code,
    width: 150,
    align: "center" as const,
    render: (_: unknown, r: PermissionRow) =>
      r.byRole[role.code] ? <CheckOutlined style={{ color: colors.success }} /> : (
        <span style={{ color: colors.muted }}>—</span>
      ),
  });

  return (
    <Card>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }} wrap>
        <Typography.Paragraph style={{ color: colors.muted, marginBottom: 0 }}>
          系统角色由代码维护;自定义角色仅支持只读权限,用于审阅和外部只读账号。
        </Typography.Paragraph>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建只读角色
        </Button>
      </Space>

      <Typography.Title level={5} style={{ marginBottom: 12 }}>
        自定义只读角色
      </Typography.Title>
      <Table<RoleOut>
        rowKey="code"
        size="small"
        columns={customColumns}
        dataSource={customRoles}
        pagination={false}
        locale={{ emptyText: "暂无自定义角色" }}
        scroll={{ x: 760 }}
        style={{ marginBottom: 32 }}
      />

      {MODULE_ORDER.map((mod) => {
        const rows = [...permIndex.values()]
          .filter((r) => r.module === mod)
          .sort((a, b) => a.code.localeCompare(b.code));
        if (!rows.length) return null;
        const rolesInModule = roles.filter((role) => rows.some((r) => r.byRole[role.code]));
        const columns: ColumnsType<PermissionRow> = [
          permColumn,
          ...rolesInModule.map(roleColumn),
        ];
        return (
          <div key={mod} style={{ marginBottom: 32 }}>
            <Typography.Title level={5} style={{ marginBottom: 12 }}>
              {MODULE_LABEL[mod] ?? mod}
            </Typography.Title>
            <Table<PermissionRow>
              rowKey="code"
              size="small"
              columns={columns}
              dataSource={rows}
              pagination={false}
              scroll={{ x: 220 + rolesInModule.length * 150 }}
            />
          </div>
        );
      })}

      <Modal
        title={editing ? `编辑角色 —— ${editing.name}` : "新建只读角色"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submitRole}
        confirmLoading={saving}
        okText="保存"
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          {!editing && (
            <Form.Item
              name="code"
              label="角色 code"
              extra="2-50 位大写字母/数字/下划线,保存后不可改"
              rules={[{ required: true, message: "请输入角色 code" }]}
            >
              <Input maxLength={50} placeholder="例如 SHAREHOLDER_VIEWER" />
            </Form.Item>
          )}
          <Form.Item
            name="name"
            label="角色名称"
            rules={[{ required: true, message: "请输入角色名称" }]}
          >
            <Input maxLength={100} placeholder="例如 股东只读" />
          </Form.Item>
          <Form.Item name="description" label="说明">
            <Input.TextArea maxLength={500} rows={3} placeholder="选填" />
          </Form.Item>
          <Form.Item
            name="permissions"
            label="只读权限"
            rules={[{ required: true, message: "请选择至少一个只读权限" }]}
          >
            <Select
              mode="multiple"
              options={assignableOptions}
              placeholder="选择可查看的模块和红线读权限"
              optionFilterProp="label"
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
