"use client";
import { ReactNode, useEffect } from "react";

import { authApi } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";

/**
 * 应用启动:若 sessionStorage 里有 access token 就拉 /auth/me 恢复会话,
 * 否则直接标记 loaded(未登录)。
 *
 * M0 基座后端无 /auth/refresh,故 token 失效(过期/401)时直接清态转登录,
 * 不做自动续期。
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const { accessToken, setUser, setLoaded, clear } = useAuthStore();

  useEffect(() => {
    (async () => {
      if (!accessToken) {
        setLoaded(true);
        return;
      }
      try {
        const me = await authApi.me();
        setUser(me);
      } catch {
        clear();
      } finally {
        setLoaded(true);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    })();
  }, []);

  return <>{children}</>;
}
