"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 供应商段权限门:supplier:read(与后端 GET /suppliers 守卫一致;后端才是安全底线)。
export default function SuppliersLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.SUPPLIER_READ]}>{children}</RouteGuard>;
}
