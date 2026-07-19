"use client";
import { ReactNode } from "react";
import { RouteGuard } from "@/components/auth/RouteGuard";

// /sales 段托管三个子应用:报价(quote:manage)/ 销售单(sales:read)/ 客户(customer:read),权限点不同。
// 故本层只做登录门;各子段权限由 quotations/orders/customers 各自 layout 精确守卫。
export default function SalesLayout({ children }: { children: ReactNode }) {
  return <RouteGuard>{children}</RouteGuard>;
}
