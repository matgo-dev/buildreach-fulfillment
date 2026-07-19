"use client";
import { ReactNode } from "react";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { App, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { colors } from "@/lib/tokens";

// 组件库 = Ant Design,主题令牌全部对齐 frontend/DESIGN.md §1(色值经 lib/tokens 单一源头),
// 不在 AntD 里另发明色值:圆角 md=6、字号 sm=14、控件高 32。
// 状态色/中性阶沿用 DESIGN §1;Table 默认无斑马,恰合 B 风格(§11.8)。
const themeConfig = {
  token: {
    colorPrimary: colors.brand, // §1.1 brand(祖母绿)
    colorLink: colors.brand,
    colorLinkHover: colors.brandLight, // brand-light
    // §1.3:成功走青,与品牌绿拉开;info 显式钉蓝 —— AntD 默认 colorInfo 跟随 colorPrimary,
    // 不钉则「处理中」类 Tag(在途/部分入库/锁档…)会一起变绿,与成功态糊成一片。
    colorSuccess: colors.success,
    colorInfo: colors.info,
    borderRadius: 6, // DESIGN §4 按钮/输入 rounded-md
    fontSize: 14, // DESIGN §2 text-sm
    controlHeight: 32,
    colorText: colors.ink, // §1.2 ink
    colorTextHeading: colors.navy, // navy
    colorBorder: colors.line, // line
  },
  // 暗色 Menu(全站唯一消费者=AppShell 侧栏):激活块走更亮的 brand-light,底色透明吃 Sider 渐变。
  components: {
    // Sider 底部折叠条不吃 Sider 的自定义背景,自带 AntD 暗蓝默认值,须显式对齐侧栏色。
    Layout: {
      triggerBg: colors.sidebarDeep,
      triggerColor: colors.sidebarText,
    },
    Menu: {
      darkItemBg: "transparent",
      darkSubMenuItemBg: "transparent",
      darkItemSelectedBg: colors.brandLight,
      darkItemColor: colors.sidebarText,
      darkGroupTitleColor: colors.sidebarGroup,
    },
  },
  algorithm: theme.defaultAlgorithm,
};

export function AntdProvider({ children }: { children: ReactNode }) {
  return (
    <AntdRegistry>
      <ConfigProvider locale={zhCN} theme={themeConfig} componentSize="middle">
        <App>{children}</App>
      </ConfigProvider>
    </AntdRegistry>
  );
}
