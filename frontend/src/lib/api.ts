// 统一的 fetch 封装。
//
// access token 纯内存(Zustand,无 Web Storage 落点),15 分钟过期;续期靠
// httpOnly refresh cookie:401 时单飞刷新(全局共享一个 refresh promise,
// 并发请求不打刷新风暴),成功重试原请求一次;失败才清态,由 RouteGuard 转登录。

import { useAuthStore } from "@/stores/authStore";
import { getApiBase } from "./env";

export class ApiError extends Error {
  code: number;
  status: number;
  traceId?: string;
  data?: unknown;

  constructor(opts: { code: number; message: string; status: number; traceId?: string; data?: unknown }) {
    super(opts.message);
    this.code = opts.code;
    this.status = opts.status;
    this.traceId = opts.traceId;
    this.data = opts.data;
  }
}

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  /** 跳过 Authorization 注入(用于登录)*/
  noAuth?: boolean;
};

// login/refresh/logout 自身不参与 401 刷新重试(refresh 失败会递归、logout 无须续命)
const REFRESH_EXEMPT_PATHS = ["/api/v1/auth/login", "/api/v1/auth/refresh", "/api/v1/auth/logout"];

let refreshPromise: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
  try {
    const res = await fetch(`${getApiBase()}/api/v1/auth/refresh`, {
      method: "POST",
      credentials: "include", // refresh token 在 httpOnly cookie 里
    });
    const json = (await res.json().catch(() => null)) as
      | { code: number; data?: { access_token?: string } }
      | null;
    if (!res.ok || !json || json.code !== 0 || !json.data?.access_token) return null;
    useAuthStore.getState().setAccessToken(json.data.access_token);
    return json.data.access_token;
  } catch {
    return null;
  }
}

/** 单飞刷新:并发 401 共享同一个进行中的 refresh 请求;成功把新 access token 写入 store。 */
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshPromise) {
    refreshPromise = doRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function request<T>(path: string, options: RequestOptions = {}, retried = false): Promise<T> {
  const { noAuth, body, headers, ...rest } = options;
  const base = getApiBase();

  const finalHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(headers as Record<string, string> | undefined),
  };

  if (!noAuth) {
    const token = useAuthStore.getState().accessToken;
    if (token) finalHeaders["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${base}${path}`, {
    ...rest,
    headers: finalHeaders,
    credentials: "include",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  let json: { code: number; message: string; data: T; trace_id?: string } | null = null;
  try {
    json = await res.json();
  } catch {
    /* 空响应体(如 204) */
  }

  if (!res.ok || !json || json.code !== 0) {
    if (!noAuth && res.status === 401 && !retried && !REFRESH_EXEMPT_PATHS.some((p) => path.startsWith(p))) {
      const token = await refreshAccessToken();
      if (token) return request<T>(path, options, true);
      // 刷新也救不回来 → 会话终止,清态交给 RouteGuard 转登录
      useAuthStore.getState().clear();
    }
    throw new ApiError({
      code: json?.code ?? res.status * 100,
      message: json?.message ?? res.statusText ?? "Request failed",
      status: res.status,
      traceId: json?.trace_id,
      data: json?.data,
    });
  }

  return json.data;
}

export const api = {
  get: <T>(path: string, options?: RequestOptions) => request<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "POST", body }),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PATCH", body }),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "PUT", body }),
  // delete 是保留字,用 del
  del: <T>(path: string, options?: RequestOptions) =>
    request<T>(path, { ...options, method: "DELETE" }),
};
