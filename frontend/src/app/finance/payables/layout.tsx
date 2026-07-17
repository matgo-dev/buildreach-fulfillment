"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { AppShell } from "@/components/layout/AppShell";
import { Permissions } from "@/config/permission-matrix";

// 财务·应付款段权限门:payable:read(与后端 GET /payables 守卫一致;整域红线,后端才是安全底线)。
export default function PayablesLayout({ children }: { children: ReactNode }) {
  return (
    <RouteGuard requiredPermissions={[Permissions.PAYABLE_READ]}>
      <AppShell breadcrumb={["财务", "应付款"]}>{children}</AppShell>
    </RouteGuard>
  );
}
