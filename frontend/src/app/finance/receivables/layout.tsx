"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 财务·应收款段权限门:receivable:read(与后端 GET /receivables 守卫一致;整域红线,后端才是安全底线)。
export default function ReceivablesLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.RECEIVABLE_READ]}>{children}</RouteGuard>;
}
