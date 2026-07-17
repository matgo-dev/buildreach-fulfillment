"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 客户段权限门:customer:read(与后端 GET /customers 守卫一致;后端才是安全底线)。
export default function CustomersLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.CUSTOMER_READ]}>{children}</RouteGuard>;
}
