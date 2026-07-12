"use client";
import { ReactNode } from "react";
import { useAuthStore } from "@/stores/authStore";

/** 权限显隐:仅 UX 友好层,后端 require_permission 才是安全底线。 */
export function Can({ perm, children }: { perm: string; children: ReactNode }) {
  const has = useAuthStore((s) => s.hasPermission(perm));
  return has ? <>{children}</> : null;
}
