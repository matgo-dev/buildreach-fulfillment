"use client";
import { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { AppShell } from "@/components/layout/AppShell";

// /sales 段托管两个子应用:报价(quote:manage)与销售单(sales:read),权限点不同。
// 故本层只做登录门 + AppShell 外壳;各子段权限由 quotations/orders 各自 layout 精确守卫。
export default function SalesLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const breadcrumb = pathname.startsWith("/sales/orders") ? ["销售单"] : ["报价管理"];
  return (
    <RouteGuard>
      <AppShell breadcrumb={breadcrumb}>{children}</AppShell>
    </RouteGuard>
  );
}
