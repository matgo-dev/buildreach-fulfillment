"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

export default function CustomerCreditsLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.RECEIVABLE_READ]}>{children}</RouteGuard>;
}
