"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 财务·付款单段权限门:payment:read(与后端 GET /payments 守卫一致;整域红线,后端才是安全底线)。
export default function PaymentsLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.PAYMENT_READ]}>{children}</RouteGuard>;
}
