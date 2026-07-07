import { create } from "zustand";
import type { MeData, RoleCode } from "@/lib/auth";

const ACCESS_TOKEN_SESSION_KEY = "fulfillment_access_token";

function readSessionAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem(ACCESS_TOKEN_SESSION_KEY);
  } catch {
    return null;
  }
}

function writeSessionAccessToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token) {
      sessionStorage.setItem(ACCESS_TOKEN_SESSION_KEY, token);
    } else {
      sessionStorage.removeItem(ACCESS_TOKEN_SESSION_KEY);
    }
  } catch {
    /* ignore storage failures */
  }
}

interface AuthState {
  /** access token 优先存内存,并在当前标签页 sessionStorage 中兜底恢复刷新 */
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
  accessToken: readSessionAccessToken(),
  user: null,
  loaded: false,
  setAccessToken: (t) => {
    writeSessionAccessToken(t);
    set({ accessToken: t });
  },
  setUser: (u) => set({ user: u }),
  setLoaded: (b) => set({ loaded: b }),
  clear: () => {
    writeSessionAccessToken(null);
    set({ accessToken: null, user: null });
  },
  hasPermission: (code) => {
    const u = get().user;
    return !!u && u.permissions.includes(code);
  },
  hasRole: (code) => {
    const u = get().user;
    return !!u && u.roles.includes(code);
  },
}));
