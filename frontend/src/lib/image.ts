import { getApiBase, getImageBackend, getImagePublicBase } from "./env";

/**
 * 由存 OSS object key 构造展示 URL(DESIGN §8):
 * - s3 公读桶:`{PUBLIC_BASE}/{key}` + `?x-oss-process=image/resize,w_{w}` 实时缩略;
 * - local:`{API_BASE}/media/{key}`(后端本地零图像处理,忽略 w)。
 * key 为空返回空串,交由调用方回退(`sku.image ?? spu.main_image`)。
 */
export function imageUrl(key: string | null | undefined, w?: number): string {
  if (!key) return "";
  if (getImageBackend() === "s3") {
    const base = getImagePublicBase().replace(/\/$/, "");
    const u = `${base}/${key}`;
    return w ? `${u}?x-oss-process=image/resize,w_${w}` : u;
  }
  return `${getApiBase()}/media/${key}`;
}
