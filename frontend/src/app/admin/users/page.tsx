"use client";
import { useCallback, useState } from "react";
import {
  App,
  Button,
  Dropdown,
  Form,
  Input,
  Modal,
  Segmented,
  Select,
  Space,
  Switch,
  Tag,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { DownOutlined, PlusOutlined } from "@ant-design/icons";
import { Drawer } from "antd";
import { StatusTag } from "@/components/common/StatusTag";
import { ListTable } from "@/components/common/ListTable";
import { ListErrorState } from "@/components/common/ListErrorState";
import { ListPageCard, ListPageBody } from "@/components/common/ListPageCard";
import { useListQuery } from "@/hooks/useListQuery";
import { useCrudDrawer } from "@/hooks/useCrudDrawer";
import { useAuthStore } from "@/stores/authStore";
import { resolveBizError } from "@/lib/errorMessages";
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

export default function UserAdminPage() {
  const { message } = App.useApp();
  const [form] = Form.useForm();
  const me = useAuthStore((s) => s.user);

  const [status, setStatus] = useState("ACTIVE");
  const [q, setQ] = useState("");
  const [rowBusyId, setRowBusyId] = useState<number | null>(null);

  // 改角色 / 重置密码 小 Modal
  const [roleTarget, setRoleTarget] = useState<UserItem | null>(null);
  const [rolePick, setRolePick] = useState<string>("");
  const [resetTarget, setResetTarget] = useState<UserItem | null>(null);
  const [resetPwd, setResetPwd] = useState("");
  const [modalBusy, setModalBusy] = useState(false);

  const fetcher = useCallback(
    ({ page, size }: { page: number; size: number }) =>
      userAdminApi.list({
        status: status || undefined,
        q: q || undefined,
        page,
        size,
      }),
    [status, q],
  );
  const { rows, setPage, loading, loadError, load, pagination } = useListQuery<UserItem>(fetcher, {
    errorMessage: "加载用户列表失败",
  });

  // 列表行即完整编辑数据(无详情接口),openEdit 直接吃行对象;回显仅取可编辑子集。
  const drawer = useCrudDrawer<UserItem, UserCreateBody & UserUpdateBody>({
    form,
    fillForm: (r) => form.setFieldsValue({ email: r.email, phone: r.phone, name: r.name }),
    prepareCreate: () => form.setFieldsValue({ must_change_password: true }),
    create: (values) => userAdminApi.create(values as UserCreateBody),
    update: (current, values) => userAdminApi.update(current.id, values as UserUpdateBody),
    afterSubmit: load,
    messages: { created: "已创建,首次登录须改密", saved: "已保存", loadFailed: "加载用户失败" },
  });
  const { mode, saving, openCreate, openEdit, closeDrawer, onSubmit } = drawer;

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
      message.error(resolveBizError(e, "操作失败"));
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
      message.error(resolveBizError(e, "改角色失败"));
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
      message.error(resolveBizError(e, "重置失败"));
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
      render: (s: UserItem["status"]) => <StatusTag meta={USER_STATUS_META} value={s} />,
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
    <ListPageCard>
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

      <ListPageBody>
        {loadError && !rows.length ? (
          <ListErrorState onRetry={load} />
        ) : (
          <ListTable<UserItem>
            rowKey="id"
            columns={columns}
            dataSource={rows}
            loading={loading}
            scroll={{ x: 900 }}
            locale={{ emptyText: "暂无用户" }}
            pagination={pagination}
          />
        )}
      </ListPageBody>

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
    </ListPageCard>
  );
}
