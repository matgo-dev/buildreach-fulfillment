"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { AppShell } from "@/components/layout/AppShell";
import { Permissions } from "@/config/permission-matrix";

// 系统段权限门:user:manage(与后端 /users 管理端点守卫一致;后端才是安全底线)。
// 单段应用,登录门 + 权限门 + AppShell 外壳合于此层(同 inbound 模式)。
export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <RouteGuard requiredPermissions={[Permissions.USER_MANAGE]}>
      <AppShell breadcrumb={["用户管理"]}>{children}</AppShell>
    </RouteGuard>
  );
}
