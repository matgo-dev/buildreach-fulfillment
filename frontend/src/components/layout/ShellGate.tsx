"use client";
import { ReactNode } from "react";
import { usePathname } from "next/navigation";
import { AppShell } from "./AppShell";
import { useAuthStore } from "@/stores/authStore";

// 无外壳路由:认证前的独立页面,没有导航可言(登录/强制改密),以及仅做重定向的首页。
const BARE_ROUTES = ["/login", "/change-password", "/"];

/**
 * 全站外壳的唯一挂载点(根 layout)。挂在根部而非各业务段 layout,
 * 是为了让跨业务域导航不卸载外壳 —— 侧栏滚动位置与折叠态因此天然保持。
 * 权限门不在这层:各业务段 layout 的 RouteGuard 仍是各自的 UX 门,后端才是安全底线。
 */
export function ShellGate({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);

  // 未登录时不套壳:此时菜单必然为空,先渲染空侧栏只会在跳登录前闪一下。
  if (!user || BARE_ROUTES.includes(pathname)) return <>{children}</>;
  return <AppShell>{children}</AppShell>;
}
