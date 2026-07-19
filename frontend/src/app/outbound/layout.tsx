"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 出库段权限门:outbound:read(与后端 GET /outbound-orders 守卫一致;后端才是安全底线)。
export default function OutboundLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.OUTBOUND_READ]}>{children}</RouteGuard>;
}
