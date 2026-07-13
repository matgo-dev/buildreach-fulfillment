"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { AppShell } from "@/components/layout/AppShell";
import { Permissions } from "@/config/permission-matrix";

export default function SalesLayout({ children }: { children: ReactNode }) {
  return (
    <RouteGuard requiredPermissions={[Permissions.QUOTE_MANAGE]}>
      <AppShell breadcrumb={["报价单"]}>{children}</AppShell>
    </RouteGuard>
  );
}
