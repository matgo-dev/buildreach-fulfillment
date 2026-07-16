"use client";
import { useCallback, useEffect, useState } from "react";
import {
  App,
  Button,
  Card,
  Dropdown,
  Form,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DownOutlined, PlusOutlined } from "@ant-design/icons";
import { Drawer } from "antd";
import { useAuthStore } from "@/stores/authStore";
import {
  ROLE_OPTIONS,
  USER_STATUS_META,
  roleLabel,
  userAdminApi,
  type UserCreateBody,
  type UserItem,
  type UserUpdateBody,
} from "@/lib/user";
import { colors } from "@/lib/tokens";

const STATUS_TABS = [
  { label: "启用", value: "ACTIVE" },
  { label: "停用", value: "DISABLED" },
  { label: "全部", value: "" },
];

type DrawerMode = "create" | "edit" | null;

export default function UserAdminPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const me = useAuthStore((s) => s.user);

  const [rows, setRows] = useState<UserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("ACTIVE");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const [mode, setMode] = useState<DrawerMode>(null);
  const [current, setCurrent] = useState<UserItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [rowBusyId, setRowBusyId] = useState<number | null>(null);

  // 改角色 / 重置密码 小 Modal
  const [roleTarget, setRoleTarget] = useState<UserItem | null>(null);
  const [rolePick, setRolePick] = useState<string>("");
  const [resetTarget, setResetTarget] = useState<UserItem | null>(null);
  const [resetPwd, setResetPwd] = useState("");
  const [modalBusy, setModalBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const res = await userAdminApi.list({
        status: status || undefined,
        q: q || undefined,
        page,
        size: 20,
      });
      setRows(res.items);
      setTotal(res.total);
    } catch (e) {
      setLoadError(true);
      message.error(e instanceof Error ? e.message : "加载用户列表失败");
    } finally {
      setLoading(false);
    }
  }, [status, q, page, message]);

  useEffect(() => {
    load();
  }, [load]);

  function openCreate() {
    setCurrent(null);
    form.resetFields();
    form.setFieldsValue({ must_change_password: true });
    setMode("create");
  }

  function openEdit(r: UserItem) {
    setCurrent(r);
    form.setFieldsValue({ email: r.email, phone: r.phone, name: r.name });
    setMode("edit");
  }

  function closeDrawer() {
    setMode(null);
    setCurrent(null);
    form.resetFields();
  }

  async function onSubmit() {
    let values: UserCreateBody & UserUpdateBody;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    setSaving(true);
    try {
      if (mode === "create") {
        await userAdminApi.create(values as UserCreateBody);
        message.success("已创建,首次登录须改密");
      } else if (mode === "edit" && current) {
        await userAdminApi.update(current.id, values as UserUpdateBody);
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

  async function toggleStatus(r: UserItem) {
    setRowBusyId(r.id);
    try {
      if (r.status === "ACTIVE") {
        await userAdminApi.disable(r.id);
        message.success("已停用");
      } else {
        await userAdminApi.enable(r.id);
        message.success("已启用");
      }
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "操作失败");
    } finally {
      setRowBusyId(null);
    }
  }

  async function onChangeRole() {
    if (!roleTarget || !rolePick) return;
    setModalBusy(true);
    try {
      await userAdminApi.changeRole(roleTarget.id, rolePick);
      message.success("角色已更新,即时生效");
      setRoleTarget(null);
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "改角色失败");
    } finally {
      setModalBusy(false);
    }
  }

  async function onResetPassword() {
    if (!resetTarget || !resetPwd) return;
    setModalBusy(true);
    try {
      await userAdminApi.resetPassword(resetTarget.id, resetPwd);
      message.success("已重置,旧会话已全部失效,首次登录须改密");
      setResetTarget(null);
      setResetPwd("");
      load();
    } catch (e) {
      message.error(e instanceof Error ? e.message : "重置失败");
    } finally {
      setModalBusy(false);
    }
  }

  const columns: ColumnsType<UserItem> = [
    { title: "姓名", dataIndex: "name", width: 140, ellipsis: true },
    { title: "邮箱", dataIndex: "email", ellipsis: true, render: (v) => v || "—" },
    { title: "用户名", dataIndex: "username", width: 120, render: (v) => v || "—" },
    {
      title: "角色",
      dataIndex: "roles",
      width: 120,
      render: (roles: string[]) =>
        roles.length ? roles.map((r) => <Tag key={r}>{roleLabel(r)}</Tag>) : "—",
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 90,
      render: (s: UserItem["status"]) => {
        const m = USER_STATUS_META[s];
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 170,
      fixed: "right" as const,
      className: "whitespace-nowrap",
      render: (_: unknown, r: UserItem) => {
        const isSelf = me?.id === r.id;
        return (
          <Space size="small">
            <Button type="link" size="small" onClick={() => openEdit(r)}>
              编辑
            </Button>
            <Dropdown
              menu={{
                items: [
                  { key: "role", label: "改角色", disabled: isSelf },
                  { key: "reset", label: "重置密码", disabled: isSelf },
                  {
                    key: "toggle",
                    label: r.status === "ACTIVE" ? "停用" : "启用",
                    danger: r.status === "ACTIVE",
                    disabled: isSelf,
                  },
                ],
                onClick: ({ key }) => {
                  if (key === "role") {
                    setRolePick(r.roles[0] ?? "");
                    setRoleTarget(r);
                  } else if (key === "reset") {
                    setResetPwd("");
                    setResetTarget(r);
                  } else if (key === "toggle") {
                    Modal.confirm({
                      title: r.status === "ACTIVE" ? "停用该账号?" : "启用该账号?",
                      content:
                        r.status === "ACTIVE"
                          ? "停用后该账号无法登录,历史单据归属不受影响。"
                          : "启用后该账号可正常登录。",
                      okButtonProps: { danger: r.status === "ACTIVE" },
                      onOk: () => toggleStatus(r),
                    });
                  }
                },
              }}
            >
              <Button type="link" size="small" loading={rowBusyId === r.id}>
                更多 <DownOutlined />
              </Button>
            </Dropdown>
          </Space>
        );
      },
    },
  ];

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
            placeholder="姓名 / 邮箱 / 用户名"
            allowClear
            style={{ width: 240 }}
            onSearch={(v) => {
              setQ(v);
              setPage(1);
            }}
          />
        </Space>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          新建用户
        </Button>
      </Space>

      {loadError && !rows.length ? (
        <div style={{ textAlign: "center", padding: "48px 0", color: colors.muted }}>
          加载失败
          <div style={{ marginTop: 12 }}>
            <Button onClick={load}>重试</Button>
          </div>
        </div>
      ) : (
        <Table<UserItem>
          rowKey="id"
          columns={columns}
          dataSource={rows}
          loading={loading}
          scroll={{ x: 900 }}
          locale={{ emptyText: "暂无用户" }}
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
        title={mode === "create" ? "新建用户" : "编辑用户"}
        open={mode !== null}
        onClose={closeDrawer}
        width="min(520px, 92vw)"
        destroyOnClose
        footer={
          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button onClick={closeDrawer} disabled={saving}>
              取消
            </Button>
            <Button type="primary" loading={saving} onClick={onSubmit}>
              保存
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="name"
            label="姓名"
            rules={[{ required: true, message: "请输入姓名" }]}
          >
            <Input maxLength={100} placeholder="真实姓名" />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱(登录凭证)"
            rules={[
              { required: mode === "create", message: "请输入邮箱" },
              { type: "email", message: "邮箱格式不正确" },
            ]}
          >
            <Input maxLength={255} placeholder="name@example.com" />
          </Form.Item>
          {mode === "create" ? (
            <>
              <Form.Item name="username" label="用户名(选填,可作登录凭证)">
                <Input maxLength={50} placeholder="选填" />
              </Form.Item>
              <Form.Item
                name="password"
                label="初始密码"
                extra="6-20 位,仅限字母和数字"
                rules={[{ required: true, message: "请输入初始密码" }]}
              >
                <Input.Password maxLength={20} placeholder="交付给用户的临时密码" />
              </Form.Item>
              <Form.Item
                name="role"
                label="角色"
                rules={[{ required: true, message: "请选择角色" }]}
              >
                <Select options={ROLE_OPTIONS} placeholder="选择角色" />
              </Form.Item>
              <Form.Item
                name="must_change_password"
                label="首次登录强制改密"
                valuePropName="checked"
                style={{ marginBottom: 0 }}
              >
                <Switch defaultChecked />
              </Form.Item>
            </>
          ) : (
            <Form.Item name="phone" label="手机号" style={{ marginBottom: 0 }}>
              <Input maxLength={30} placeholder="选填" />
            </Form.Item>
          )}
        </Form>
      </Drawer>

      <Modal
        title={`改角色 —— ${roleTarget?.name ?? ""}`}
        open={roleTarget !== null}
        onCancel={() => setRoleTarget(null)}
        onOk={onChangeRole}
        confirmLoading={modalBusy}
        okText="确认更换"
        destroyOnClose
      >
        <p style={{ color: colors.muted, marginBottom: 12 }}>
          权限即时生效,无需该用户重新登录。
        </p>
        <Select
          style={{ width: "100%" }}
          options={ROLE_OPTIONS}
          value={rolePick || undefined}
          onChange={setRolePick}
          placeholder="选择新角色"
        />
      </Modal>

      <Modal
        title={`重置密码 —— ${resetTarget?.name ?? ""}`}
        open={resetTarget !== null}
        onCancel={() => setResetTarget(null)}
        onOk={onResetPassword}
        confirmLoading={modalBusy}
        okText="确认重置"
        okButtonProps={{ danger: true }}
        destroyOnClose
      >
        <p style={{ color: colors.muted, marginBottom: 12 }}>
          重置后该用户全部旧会话立即失效,须用临时密码登录并改密。
        </p>
        <Input.Password
          maxLength={20}
          placeholder="新临时密码(6-20 位字母数字)"
          value={resetPwd}
          onChange={(e) => setResetPwd(e.target.value)}
        />
      </Modal>
    </Card>
  );
}
