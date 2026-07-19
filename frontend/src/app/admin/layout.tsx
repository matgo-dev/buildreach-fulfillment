"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 系统段权限门:user:manage(与后端 /users 管理端点守卫一致;后端才是安全底线)。
// 单段应用,登录门 + 权限门合于此层(同 inbound 模式);外壳由根 layout 的 ShellGate 统一提供。
export default function AdminLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.USER_MANAGE]}>{children}</RouteGuard>;
}
