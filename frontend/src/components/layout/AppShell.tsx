"use client";
import { ReactNode, useEffect, useState } from "react";
import { Layout, Menu, Breadcrumb, Dropdown, Avatar, Button } from "antd";
import {
  UserOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import { usePathname, useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/authStore";
import { authApi } from "@/lib/auth";
import { getVisibleMenuGroups } from "@/config/navigation";
import { colors } from "@/lib/tokens";

const { Header, Sider, Content } = Layout;

// 侧栏暗色底 = DESIGN §1.1 sidebar(深墨绿;与 AntD 默认 #001529 的有意偏离)。

/**
 * 全站唯一外壳实例(挂在根 layout 的 ShellGate 上,业务段 layout 只留 RouteGuard)。
 * 单实例是硬要求:外壳若按业务域各挂一个,跨域导航会整体重挂,侧栏滚动位置与折叠态每次归零。
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const router = useRouter();
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const clear = useAuthStore((s) => s.clear);
  const hasPermission = useAuthStore((s) => s.hasPermission);

  // 按权限过滤菜单项(perm === null → 恒可见,如「平台导览」);整组被过滤空 → 该组标题一并隐藏。
  const visibleGroups = getVisibleMenuGroups(hasPermission);
  const visibleItems = visibleGroups.flatMap((g) => g.items);

  // 详情页(/catalog/spus/123)仍高亮所属一级项:取最长前缀命中。
  const selectedKey =
    visibleItems
      .map((m) => m.key)
      .filter((k) => pathname === k || pathname.startsWith(k + "/"))
      .sort((a, b) => b.length - a.length)[0] ?? pathname;

  // 面包屑从菜单结构派生(组名 + 菜单标签),不再由各业务段 layout 各写一份手抄值 —— 单一源头。
  const currentGroup = visibleGroups.find((g) => g.items.some((m) => m.key === selectedKey));
  const currentItem = visibleItems.find((m) => m.key === selectedKey);
  const breadcrumb = currentItem
    ? [currentGroup?.group, currentItem.label].filter((s): s is string => Boolean(s))
    : [];

  // 全站页面均为客户端组件(Next `metadata` 不生效),故页签标题集中设在此,
  // 保证并行开多页签各不同名。依赖收敛成字符串:visibleItems 每渲染都是新数组,直接进 deps 会每帧重跑。
  const titleLabel = currentItem?.label;
  useEffect(() => {
    document.title = titleLabel ? `${titleLabel} · 履约系统` : "履约系统";
  }, [titleLabel]);

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
    <Layout style={{ height: "100vh", overflow: "hidden" }}>
      {/* 侧栏钉住视口:内容区再长也不带着导航滚;菜单超高时只在菜单区内部滚。 */}
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        // 168 而非 AntD 默认 200:菜单标签最长 4 个汉字(商品目录/报价管理/用户管理),
        // 200 会在右侧留下一条明显的空白带;168 = 图标+4字+两侧留白后仍有余量,不会挤或换行。
        width={168}
        // trigger={null}:AntD 自带的底部折叠条会在侧栏底部压出一条与背景同色的死区,
        // 既浪费高度又不像可点控件;折叠按钮改放顶栏左侧(现代 admin 通行做法)。
        trigger={null}
        style={{ background: colors.sidebar, position: "sticky", top: 0, height: "100vh" }}
      >
        <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
          {/* 品牌区:与菜单项 icon 起点(24px)对齐的紧凑行 + 底部发丝线与菜单分隔 */}
          <div
            style={{
              height: 48,
              flex: "0 0 auto",
              display: "flex",
              alignItems: "center",
              justifyContent: collapsed ? "center" : "flex-start",
              paddingLeft: collapsed ? 0 : 24,
              marginBottom: 4,
              borderBottom: `1px solid ${colors.sidebarLine}`,
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
            style={{
              background: "transparent",
              flex: "1 1 auto",
              overflowY: "auto",
              overflowX: "hidden",
            }}
            selectedKeys={[selectedKey]}
            // 折叠态下分组标题只剩噪声(仅余图标),此时铺平只留菜单项。
            items={
              collapsed
                ? visibleItems.map((m) => ({
                    key: m.key,
                    icon: m.icon,
                    label: m.label,
                  }))
                : visibleGroups.map((g) => ({
                    key: `group:${g.group}`,
                    type: "group" as const,
                    label: g.group,
                    children: g.items.map((m) => ({
                      key: m.key,
                      icon: m.icon,
                      label: m.label,
                    })),
                  }))
            }
            onClick={({ key }) => router.push(key)}
          />
        </div>
      </Sider>
      <Layout>
        <Header
          style={{
            background: colors.white,
            borderBottom: `1px solid ${colors.line}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            paddingInline: 16,
          }}
        >
          <Button
            type="text"
            aria-label={collapsed ? "展开导航" : "收起导航"}
            icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
            onClick={() => setCollapsed((v) => !v)}
          />
          <Dropdown
            menu={{
              items: [
                {
                  key: "logout",
                  icon: <LogoutOutlined />,
                  label: "登出",
                  onClick: onLogout,
                },
              ],
            }}
          >
            <span style={{ cursor: "pointer", color: colors.ink }}>
              <Avatar size="small" icon={<UserOutlined />} /> {user?.name}
            </span>
          </Dropdown>
        </Header>
        {/*
          固定外壳:内容区吃满「视口 − 顶栏」的确定高度,自身不滚(overflow:hidden)。
          - 面包屑固定在顶(flex-none)。
          - children 装在默认可滚区(overflow-y:auto):详情/表单页内容高就在这里滚,零改动。
          - 列表页则让其根 Card 撑满高度、由 ListTable 在内部滚表体 —— Card 恰好填满、外层不滚,只表体滚。
        */}
        <Content
          style={{
            display: "flex",
            flexDirection: "column",
            height: "100%",
            minHeight: 0,
            padding: 16,
            overflow: "hidden",
          }}
        >
          {breadcrumb.length > 0 && (
            <Breadcrumb
              style={{ marginBottom: 12, flex: "0 0 auto" }}
              items={breadcrumb.map((b) => ({ title: b }))}
            />
          )}
          <div style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto" }}>{children}</div>
        </Content>
      </Layout>
    </Layout>
  );
}
