import type { Metadata } from "next";
import Script from "next/script";
import { ReactNode } from "react";

import { AntdProvider } from "@/components/providers/AntdProvider";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { ShellGate } from "@/components/layout/ShellGate";
import "./globals.css";

export const metadata: Metadata = {
  title: "Fulfillment",
  description: "履约系统 M0 基座",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh">
      <body>
        {/* 运行时环境注入:容器 entrypoint 生成 /__env.js → window.__ENV(API_BASE_URL 等)。
            须 beforeInteractive,早于应用代码读取。 */}
        <Script src="/__env.js" strategy="beforeInteractive" />
        <AntdProvider>
          <AuthProvider>
            <ShellGate>{children}</ShellGate>
          </AuthProvider>
        </AntdProvider>
      </body>
    </html>
  );
}
