"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 库存段权限门:inventory:read(与后端 GET /inventory 守卫一致;后端才是安全底线)。
// 单段应用,故登录门 + 权限门合于此层;外壳由根 layout 的 ShellGate 统一提供。
export default function InventoryLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.INVENTORY_READ]}>{children}</RouteGuard>;
}
