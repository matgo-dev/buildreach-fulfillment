"use client";
import { ReactNode, useState } from "react";
import { Layout, Menu, Breadcrumb, Dropdown, Avatar } from "antd";
import {
  AppstoreOutlined,
  FileTextOutlined,
  InboxOutlined,
  ProfileOutlined,
  ShopOutlined,
  ShoppingCartOutlined,
  AccountBookOutlined,
  TeamOutlined,
  UserOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  DatabaseOutlined,
  ExportOutlined,
  ContainerOutlined,
} from "@ant-design/icons";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/authStore";
import { authApi } from "@/lib/auth";
import { Permissions } from "@/config/permission-matrix";
import { colors } from "@/lib/tokens";

const { Header, Sider, Content } = Layout;

// 侧栏暗色底 = DESIGN §1.1 sidebar(与 AntD 默认 #001529 的有意偏离)。
const SIDER_BG = colors.sidebar;

// 菜单项按权限显隐(perm=可见所需权限点),避免死链;后端 RouteGuard 仍是访问底线。
const MENU_ITEMS = [
  { key: "/catalog/spus", icon: <AppstoreOutlined />, label: "商品目录", perm: Permissions.PRODUCT_READ },
  { key: "/sales/customers", icon: <TeamOutlined />, label: "客户", perm: Permissions.CUSTOMER_READ },
  { key: "/sales/quotations", icon: <FileTextOutlined />, label: "报价管理", perm: Permissions.QUOTE_MANAGE },
  { key: "/sales/orders", icon: <ProfileOutlined />, label: "销售单", perm: Permissions.SALES_READ },
  { key: "/purchasing/suppliers", icon: <ShopOutlined />, label: "供应商", perm: Permissions.SUPPLIER_READ },
  { key: "/purchasing/orders", icon: <ShoppingCartOutlined />, label: "采购单", perm: Permissions.PURCHASE_READ },
  { key: "/inbound", icon: <InboxOutlined />, label: "入库单", perm: Permissions.INBOUND_READ },
  { key: "/inventory", icon: <DatabaseOutlined />, label: "库存", perm: Permissions.INVENTORY_READ },
  { key: "/outbound", icon: <ExportOutlined />, label: "出库单", perm: Permissions.OUTBOUND_READ },
  { key: "/shipments", icon: <ContainerOutlined />, label: "发运柜", perm: Permissions.SHIPMENT_READ },
  { key: "/finance/payables", icon: <AccountBookOutlined />, label: "财务·应付款", perm: Permissions.PAYABLE_READ },
  { key: "/finance/receivables", icon: <AccountBookOutlined />, label: "财务·应收款", perm: Permissions.RECEIVABLE_READ },
  { key: "/admin/users", icon: <SafetyCertificateOutlined />, label: "用户管理", perm: Permissions.USER_MANAGE },
];

export function AppShell({ children, breadcrumb = [] }: { children: ReactNode; breadcrumb?: string[] }) {
  const [collapsed, setCollapsed] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);
  const hasPermission = useAuthStore((s) => s.hasPermission);

  // 按权限过滤菜单项(perm 缺省=始终显示)。
  const visibleItems = MENU_ITEMS.filter((m) => !m.perm || hasPermission(m.perm));

  // 详情页(/catalog/spus/123)仍高亮所属一级项:取最长前缀命中。
  const selectedKey =
    visibleItems
      .map((m) => m.key)
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
        {/* 品牌区:与菜单项 icon 起点(24px)对齐的紧凑行 + 底部发丝线与菜单分隔 */}
        <div
          style={{
            height: 56,
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed ? "center" : "flex-start",
            paddingLeft: collapsed ? 0 : 24,
            marginBottom: 4,
            borderBottom: "1px solid rgba(255,255,255,0.08)",
            color: colors.white,
            fontSize: 15,
            fontWeight: 600,
            letterSpacing: 1,
            whiteSpace: "nowrap",
          }}
        >
          {collapsed ? "履约" : "履约系统"}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          style={{ background: "transparent" }}
          selectedKeys={[selectedKey]}
          items={visibleItems.map((m) => ({ key: m.key, icon: m.icon, label: m.label }))}
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
