"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 入库段权限门:inbound:read(与后端 GET /inbound-orders 守卫一致;后端才是安全底线)。
// 单段应用,故登录门 + 权限门合于此层;外壳由根 layout 的 ShellGate 统一提供。
export default function InboundLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.INBOUND_READ]}>{children}</RouteGuard>;
}
