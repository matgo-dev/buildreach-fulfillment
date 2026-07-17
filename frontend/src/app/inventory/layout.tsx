"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { AppShell } from "@/components/layout/AppShell";
import { Permissions } from "@/config/permission-matrix";

// 库存段权限门:inventory:read(与后端 GET /inventory 守卫一致;后端才是安全底线)。
// 单段应用,故登录门 + 权限门 + AppShell 外壳合于此层。
export default function InventoryLayout({ children }: { children: ReactNode }) {
  return (
    <RouteGuard requiredPermissions={[Permissions.INVENTORY_READ]}>
      <AppShell breadcrumb={["库存"]}>{children}</AppShell>
    </RouteGuard>
  );
}
