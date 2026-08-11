import { getApiBase } from "./env";

/**
 * 由存储 object key 构造受控读取 URL。
 *
 * 业务图片默认不公开,前端必须用 authFetch 带 Bearer 拉 blob;不要把返回值直接放进
 * `<img src>`。存储可以是 local/MinIO/OVH Object Storage,访问入口始终由后端鉴权代理。
 * 标准 S3 兼容存储无 URL 传参改尺寸能力,`w` 忽略(需缩略走上传预生成或独立图片服务)。
 * key 为空返回空串,交由调用方回退(`sku.image ?? spu.main_image`)。
 */
export function imageUrl(key: string | null | undefined, w?: number): string {
  void w; // 保留形参兼容调用方;当前各后端均不做 URL 传参改尺寸
  if (!key) return "";
  return `${getApiBase()}/api/v1/media/${key}`;
}
