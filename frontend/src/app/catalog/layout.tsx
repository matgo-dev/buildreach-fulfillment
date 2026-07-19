"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { Permissions } from "@/config/permission-matrix";

export default function CatalogLayout({ children }: { children: ReactNode }) {
  return <RouteGuard requiredPermissions={[Permissions.PRODUCT_READ]}>{children}</RouteGuard>;
}
