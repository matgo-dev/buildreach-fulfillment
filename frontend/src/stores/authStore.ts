import { create } from "zustand";
import type { MeData, RoleCode } from "@/lib/auth";

interface AuthState {
  /** access token 纯内存(无任何 Web Storage 落点,XSS 可读面最小化);刷新页面靠 httpOnly refresh cookie 恢复 */
  accessToken: string | null;
  user: MeData | null;
  loaded: boolean;

  setAccessToken: (t: string | null) => void;
  setUser: (u: MeData | null) => void;
  setLoaded: (b: boolean) => void;
  /** 清掉所有 auth 状态(登出 / 会话失效 用)*/
  clear: () => void;

  hasPermission: (code: string) => boolean;
  hasRole: (code: RoleCode) => boolean;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  loaded: false,
  setAccessToken: (t) => set({ accessToken: t }),
  setUser: (u) => set({ user: u }),
  setLoaded: (b) => set({ loaded: b }),
  clear: () => set({ accessToken: null, user: null }),
  hasPermission: (code) => {
    const u = get().user;
    return !!u && u.permissions.includes(code);
  },
  hasRole: (code) => {
    const u = get().user;
    return !!u && u.roles.includes(code);
  },
}));
