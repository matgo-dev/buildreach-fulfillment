"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

// 报价段权限门:quote:manage(后端 require_permission 才是安全底线,此处仅 UX)。
export default function QuotationsLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.QUOTE_MANAGE]}>{children}</RouteGuard>;
}
