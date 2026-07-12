import { api } from "./api";
import { getApiBase } from "./env";
import { useAuthStore } from "@/stores/authStore";

interface CreateUploadOut {
  key: string;
  upload_url: string;
  method: string;
}

/**
 * 商品图两步直传(DESIGN §8,一套代码兼容 OSS 直传与 local 后端 PUT):
 * 1. POST /uploads {filename, content_type} → {key, upload_url, method}
 * 2. 按 upload_url 传文件:
 *    - 绝对 URL(OSS presigned):直传,不带 Authorization;
 *    - 相对 URL(local `/api/v1/uploads/{key}`):补 API base + Bearer,经本服务落盘。
 * 成功返回 object key,业务表单只存 key(非 URL)。
 */
export async function uploadImage(file: File): Promise<string> {
  const res = await api.post<CreateUploadOut>("/api/v1/uploads", {
    filename: file.name,
    content_type: file.type,
  });

  const isAbsolute = /^https?:\/\//i.test(res.upload_url);
  const url = isAbsolute ? res.upload_url : `${getApiBase()}${res.upload_url}`;
  const headers: Record<string, string> = { "Content-Type": file.type };
  if (!isAbsolute) {
    const token = useAuthStore.getState().accessToken;
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const put = await fetch(url, {
    method: res.method || "PUT",
    headers,
    body: file,
    credentials: isAbsolute ? "omit" : "include",
  });
  if (!put.ok) throw new Error(`图片上传失败 (${put.status})`);
  return res.key;
}
