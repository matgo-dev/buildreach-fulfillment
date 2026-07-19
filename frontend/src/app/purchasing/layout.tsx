"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";

// /purchasing 段托管两个子应用:供应商(supplier:read)与采购单(purchase:read),权限点不同。
// 本层只做登录门;各子段权限由 suppliers/orders 各自 layout 精确守卫。
export default function PurchasingLayout({ children }: { children: ReactNode }) {
  return <RouteGuard>{children}</RouteGuard>;
}
