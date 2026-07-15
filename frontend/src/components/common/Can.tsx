"use client";
import { ReactNode } from "react";
import { useAuthStore } from "@/stores/authStore";

/** 权限显隐:仅 UX 友好层,后端 require_permission 才是安全底线。
 *  fallback:无权时的降级渲染(默认 null=不显示)。跨单据链接用它把「可点单号」降为纯文本
 *  ——号可见(单号非红线),但无目标页权限则不可点,避免撞 403 死链(见 DESIGN.md §7 单据链接降级)。 */
export function Can({
  perm,
  children,
  fallback = null,
}: {
  perm: string;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const has = useAuthStore((s) => s.hasPermission(perm));
  return has ? <>{children}</> : <>{fallback}</>;
}
