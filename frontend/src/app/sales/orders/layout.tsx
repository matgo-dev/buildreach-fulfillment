"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 销售单段权限门:sales:read(与后端 GET /sales-orders 守卫一致;后端才是安全底线)。
export default function SalesOrdersLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.SALES_READ]}>{children}</RouteGuard>;
}
