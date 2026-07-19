"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { useAuthStore } from "@/stores/authStore";

// 登录后落地页:直接进商品目录操作台。
// 尚无独立 dashboard,故首页即重定向;未登录由 RouteGuard 兜去 /login。
function HomeRedirect() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  useEffect(() => {
    if (user) router.replace("/catalog/spus");
  }, [user, router]);
  return null;
}

export default function HomePage() {
  return (
    <RouteGuard>
      <HomeRedirect />
    </RouteGuard>
  );
}
