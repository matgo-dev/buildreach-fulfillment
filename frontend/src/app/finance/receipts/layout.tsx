"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 财务·收款单段权限门:receipt:read(与后端 GET /receipts 守卫一致;后端才是安全底线)。
export default function ReceiptsLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.RECEIPT_READ]}>{children}</RouteGuard>;
}
