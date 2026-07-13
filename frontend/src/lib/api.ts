// 统一的 fetch 封装。
//
// M0 基座:access token 存 Zustand(内存 + sessionStorage 兜底刷新),
// 每次请求注入 Authorization。后端 M0 无 /auth/refresh,401 直接清态转登录,
// 不做自动续期(留待后续里程碑补 refresh 链路时再加)。

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

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
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
    if (!noAuth && res.status === 401) {
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
