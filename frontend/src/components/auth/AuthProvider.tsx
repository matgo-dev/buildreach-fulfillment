"use client";
import { ReactNode, useEffect } from "react";

import { refreshAccessToken } from "@/lib/api";
import { authApi } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";

/**
 * 应用启动:先调 /auth/refresh(httpOnly cookie,credentials include)换 access token,
 * 成功则拉 /auth/me 恢复会话;失败即未登录态,交给 RouteGuard 转登录。
 *
 * access token 纯内存,刷新页面靠 refresh cookie 恢复,无 Web Storage 落点。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const { setUser, setLoaded, clear } = useAuthStore();

  useEffect(() => {
    (async () => {
      try {
        const token = await refreshAccessToken();
        if (token) {
          const me = await authApi.me();
          setUser(me);
        }
      } catch {
        clear();
      } finally {
        setLoaded(true);
      }
    })();
    // 仅启动时跑一次(store setter 引用稳定,无需入依赖)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <>{children}</>;
}
