// 运行时环境变量读取。
//
// 浏览器侧优先读 window.__ENV（容器化部署可注入），SSR/开发时 fallback 到 process.env。

declare global {
  interface Window {
    __ENV?: {
      API_BASE_URL?: string;
      /** 图片存储后端:local(经后端 /media 读)| s3(公读桶直读)。默认 local。 */
      IMAGE_BACKEND?: string;
      /** s3 公读桶基址(如 https://cdn.example.com);IMAGE_BACKEND=s3 时用。 */
      IMAGE_PUBLIC_BASE?: string;
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
    // 浏览器侧只能读 NEXT_PUBLIC_ 前缀的变量,本地开发须在 .env.local 设该键。
    throw new Error("API_BASE_URL 未配置,请在 .env.local 中设置 NEXT_PUBLIC_API_BASE_URL");
  }
  return base;
}

/** 图片存储后端(local / s3)。默认 local(dev 经后端 /media 读)。 */
export function getImageBackend(): "local" | "s3" {
  const v =
    (typeof window !== "undefined" && window.__ENV?.IMAGE_BACKEND) ||
    process.env.NEXT_PUBLIC_IMAGE_BACKEND ||
    "local";
  return v === "s3" ? "s3" : "local";
}

/** s3 公读桶基址(仅 IMAGE_BACKEND=s3 时使用)。 */
export function getImagePublicBase(): string {
  return (
    (typeof window !== "undefined" && window.__ENV?.IMAGE_PUBLIC_BASE) ||
    process.env.NEXT_PUBLIC_IMAGE_PUBLIC_BASE ||
    ""
  );
}
