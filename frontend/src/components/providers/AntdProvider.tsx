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
    colorPrimary: colors.brand, // §1.1 brand
    colorLink: colors.brand,
    colorLinkHover: colors.brandMid, // brand-mid
    borderRadius: 6, // DESIGN §4 按钮/输入 rounded-md
    fontSize: 14, // DESIGN §2 text-sm
    controlHeight: 32,
    colorText: colors.ink, // §1.2 ink
    colorTextHeading: colors.navy, // navy
    colorBorder: colors.line, // line
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
