"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { AppShell } from "@/components/layout/AppShell";
import { Permissions } from "@/config/permission-matrix";

// 发运柜段权限门:shipment:read(与后端 GET /shipments 守卫一致;后端才是安全底线)。
export default function ShipmentsLayout({ children }: { children: ReactNode }) {
  return (
    <RouteGuard requiredPermissions={[Permissions.SHIPMENT_READ]}>
      <AppShell breadcrumb={["发运柜"]}>{children}</AppShell>
    </RouteGuard>
  );
}
