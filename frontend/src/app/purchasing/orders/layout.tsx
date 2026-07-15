"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 采购单段权限门:purchase:read(与后端 GET /purchase-orders 守卫一致;后端才是安全底线)。
export default function PurchaseOrdersLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.PURCHASE_READ]}>{children}</RouteGuard>;
}
