"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { AppShell } from "@/components/layout/AppShell";
import { Permissions } from "@/config/permission-matrix";

export default function CatalogLayout({ children }: { children: ReactNode }) {
  return (
    <RouteGuard requiredPermissions={[Permissions.PRODUCT_READ]}>
      <AppShell breadcrumb={["商品目录"]}>{children}</AppShell>
    </RouteGuard>
  );
}
