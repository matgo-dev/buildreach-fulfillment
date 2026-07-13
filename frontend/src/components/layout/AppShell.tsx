"use client";
import { ReactNode, useState } from "react";
import { Layout, Menu, Breadcrumb, Dropdown, Avatar } from "antd";
import { AppstoreOutlined, UserOutlined, LogoutOutlined } from "@ant-design/icons";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/authStore";
import { authApi } from "@/lib/auth";
import { colors } from "@/lib/tokens";

const { Header, Sider, Content } = Layout;

// 侧栏暗色底 = DESIGN §1.1 sidebar(与 AntD 默认 #001529 的有意偏离)。
const SIDER_BG = colors.sidebar;

// SKU 维度搜索能力(/catalog/skus 路由仍在)留给「报价」等 SKU 级操作,不在目录侧栏单列入口。
const MENU_ITEMS = [
  { key: "/catalog/spus", icon: <AppstoreOutlined />, label: "商品目录" },
];

export function AppShell({ children, breadcrumb = [] }: { children: ReactNode; breadcrumb?: string[] }) {
  const [collapsed, setCollapsed] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);

  // 详情页(/catalog/spus/123)仍高亮所属一级项:取最长前缀命中。
  const selectedKey =
    MENU_ITEMS.map((m) => m.key)
      .filter((k) => pathname === k || pathname.startsWith(k + "/"))
      .sort((a, b) => b.length - a.length)[0] ?? pathname;

  async function onLogout() {
    try {
      await authApi.logout();
    } catch {
      /* 登出失败也清本地态 */
    }
    clear();
    router.replace("/login");
  }

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} style={{ background: SIDER_BG }}>
        <div
          style={{
            height: 48,
            margin: 8,
            color: colors.white,
            fontWeight: 700,
            textAlign: "center",
            lineHeight: "32px",
            letterSpacing: collapsed ? 0 : 2,
          }}
        >
          {collapsed ? "履约" : "履约系统"}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          style={{ background: "transparent" }}
          selectedKeys={[selectedKey]}
          items={MENU_ITEMS}
          onClick={({ key }) => router.push(key)}
        />
      </Sider>
      <Layout>
        <Header
          style={{
            background: colors.white,
            borderBottom: `1px solid ${colors.line}`,
            display: "flex",
            justifyContent: "flex-end",
            alignItems: "center",
            paddingInline: 16,
          }}
        >
          <Dropdown
            menu={{
              items: [{ key: "logout", icon: <LogoutOutlined />, label: "登出", onClick: onLogout }],
            }}
          >
            <span style={{ cursor: "pointer", color: colors.ink }}>
              <Avatar size="small" icon={<UserOutlined />} /> {user?.name}
            </span>
          </Dropdown>
        </Header>
        <Content style={{ margin: 16 }}>
          {breadcrumb.length > 0 && (
            <Breadcrumb style={{ marginBottom: 12 }} items={breadcrumb.map((b) => ({ title: b }))} />
          )}
          {children}
        </Content>
      </Layout>
    </Layout>
  );
}
