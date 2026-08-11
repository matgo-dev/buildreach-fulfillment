"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { App, Button, Card, Descriptions, Form, Input, Space } from "antd";
import { KeyOutlined, SaveOutlined } from "@ant-design/icons";

import { RouteGuard } from "@/components/auth/RouteGuard";
import { ApiError } from "@/lib/api";
import { authApi, type SelfProfileUpdateBody } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";

function ProfileContent() {
  const router = useRouter();
  const { message } = App.useApp();
  const [form] = Form.useForm<SelfProfileUpdateBody>();
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!user) return;
    form.setFieldsValue({
      email: user.email ?? "",
      username: user.username ?? "",
      phone: user.phone ?? "",
      name: user.name,
    });
  }, [form, user]);

  async function onFinish(values: SelfProfileUpdateBody) {
    setSaving(true);
    try {
      const next = await authApi.updateMe({
        email: values.email?.trim() || null,
        username: values.username?.trim() ?? "",
        phone: values.phone?.trim() ?? "",
        name: values.name?.trim() || null,
      });
      setUser(next);
      message.success("个人资料已保存");
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{ maxWidth: 880 }}>
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Card
          size="small"
          title="个人资料"
          extra={
            <Button icon={<KeyOutlined />} onClick={() => router.push("/change-password")}>
              修改密码
            </Button>
          }
        >
          <Descriptions size="small" column={2} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="用户 ID">{user?.id}</Descriptions.Item>
            <Descriptions.Item label="角色">{user?.roles.join(", ") || "—"}</Descriptions.Item>
          </Descriptions>

          <Form form={form} layout="vertical" onFinish={onFinish} style={{ maxWidth: 560 }}>
            <Form.Item name="name" label="姓名" rules={[{ required: true, message: "请输入姓名" }]}>
              <Input maxLength={100} />
            </Form.Item>
            <Form.Item
              name="email"
              label="邮箱"
              rules={[
                { required: true, message: "请输入邮箱" },
                { type: "email", message: "邮箱格式不正确" },
              ]}
            >
              <Input maxLength={255} />
            </Form.Item>
            <Form.Item name="username" label="用户名">
              <Input maxLength={50} />
            </Form.Item>
            <Form.Item name="phone" label="手机号">
              <Input maxLength={30} />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={saving} icon={<SaveOutlined />}>
              保存
            </Button>
          </Form>
        </Card>
      </Space>
    </div>
  );
}

export default function ProfilePage() {
  return (
    <RouteGuard>
      <ProfileContent />
    </RouteGuard>
  );
}
