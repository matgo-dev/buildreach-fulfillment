import type { Metadata } from "next";
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
        <AntdProvider>
          <AuthProvider>
            <ShellGate>{children}</ShellGate>
          </AuthProvider>
        </AntdProvider>
      </body>
    </html>
  );
}
