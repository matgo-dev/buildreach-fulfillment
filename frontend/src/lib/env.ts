// 运行时环境变量读取。
//
// 浏览器侧优先读 window.__ENV（容器化部署可注入），SSR/开发时 fallback 到 process.env。

declare global {
  interface Window {
    __ENV?: {
      API_BASE_URL?: string;
    };
  }
}

/**
 * 获取 API 基础地址(浏览器访问后端的公网地址)。
 *
 * 优先级:window.__ENV.API_BASE_URL > process.env.API_BASE_URL > process.env.NEXT_PUBLIC_API_BASE_URL
 * 未配置时抛错,不提供默认值,避免静默连错端口。
 */
export function getApiBase(): string {
  if (typeof window !== "undefined" && window.__ENV?.API_BASE_URL) {
    return window.__ENV.API_BASE_URL;
  }
  const base = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!base) {
    throw new Error("API_BASE_URL 未配置,请在 .env.local 中设置 API_BASE_URL");
  }
  return base;
}
