import { getApiBase, getImageBackend, getImagePublicBase } from "./env";

/**
 * 由存储 object key 构造展示 URL:
 * - s3 公读桶(IMAGE_BACKEND=s3,如接了公读 CDN):`{PUBLIC_BASE}/{key}` 直连;
 * - 默认 local:`{API_BASE}/media/{key}`,由后端代理(本地盘 or 私有对象存储均可,见 media.py)。
 * 标准 S3 兼容存储无 URL 传参改尺寸能力,`w` 忽略(需缩略走上传预生成或独立图片服务)。
 * key 为空返回空串,交由调用方回退(`sku.image ?? spu.main_image`)。
 */
export function imageUrl(key: string | null | undefined, w?: number): string {
  void w; // 保留形参兼容调用方;当前各后端均不做 URL 传参改尺寸
  if (!key) return "";
  if (getImageBackend() === "s3") {
    const base = getImagePublicBase().replace(/\/$/, "");
    return `${base}/${key}`;
  }
  return `${getApiBase()}/media/${key}`;
}
