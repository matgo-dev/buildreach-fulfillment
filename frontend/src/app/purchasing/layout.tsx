"use client";
import { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { AppShell } from "@/components/layout/AppShell";

// /purchasing 段托管两个子应用:供应商(supplier:read)与采购单(purchase:read),权限点不同。
// 本层只做登录门 + AppShell 外壳;各子段权限由 suppliers/orders 各自 layout 精确守卫。
export default function PurchasingLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const breadcrumb = pathname.startsWith("/purchasing/orders") ? ["采购单"] : ["供应商"];
  return (
    <RouteGuard>
      <AppShell breadcrumb={breadcrumb}>{children}</AppShell>
    </RouteGuard>
  );
}
