"use client";
import { ReactNode } from "react";
import { AntdRegistry } from "@ant-design/nextjs-registry";
import { App, ConfigProvider, theme } from "antd";
import zhCN from "antd/locale/zh_CN";

// 组件库 = Ant Design,主题令牌全部对齐 frontend/DESIGN.md(唯一源头),
// 不在 AntD 里另发明色值:主色 brand #003366、圆角 md=6、字号 sm=14、控件高 32。
// 状态色/中性阶沿用 DESIGN §1;Table 默认无斑马,恰合 B 风格(§11.8)。
const themeConfig = {
  token: {
    colorPrimary: "#003366", // DESIGN §1.1 brand
    colorLink: "#003366",
    colorLinkHover: "#0F4C81", // brand-mid
    borderRadius: 6, // DESIGN §4 按钮/输入 rounded-md
    fontSize: 14, // DESIGN §2 text-sm
    controlHeight: 32,
    colorText: "#1c314f", // DESIGN §1.2 ink
    colorTextHeading: "#102441", // navy
    colorBorder: "#dbe4ea", // line
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
