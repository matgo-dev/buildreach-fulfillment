// 报关附件(报关单/放行扫描件)前端接入。中转上传 + 鉴权下载。
// 直传/下载走裸 fetch + Bearer(与 upload.ts 同口径),不经 api.ts 的 JSON 包装:
// - 上传 POST /api/v1/attachments 仍返回 {code,message,data},手动解包 data;
// - 下载 GET .../download 是鉴权流式响应(非 JSON),取 blob 触发浏览器另存。
import { getApiBase } from "./env";
import { useAuthStore } from "@/stores/authStore";
import type { AttachmentPublic } from "./shipment";

// 前端预校验对齐后端白名单(超限/类型先拦,减少无谓上传)。
export const ALLOWED_EXTS = [
  ".pdf", ".jpg", ".jpeg", ".png", ".webp",
  ".xlsx", ".xls", ".docx", ".doc", ".zip", ".rar",
];
export const MAX_SIZE = 50 * 1024 * 1024; // 50MB
export const MAX_ATTACHMENTS = 10;

/** 文件大小人类可读(下载列表展示)。 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  return `${(kb / 1024).toFixed(1)} MB`;
}

/** 预校验:通过返回 null,不通过返回中文错误串。 */
export function validateFile(file: File): string | null {
  const name = file.name.toLowerCase();
  const dot = name.lastIndexOf(".");
  const ext = dot >= 0 ? name.slice(dot) : "";
  if (!ALLOWED_EXTS.includes(ext)) {
    return `不支持的文件类型(仅 ${ALLOWED_EXTS.join(" / ")})`;
  }
  if (file.size > MAX_SIZE) {
    return `文件超过大小上限(${formatFileSize(MAX_SIZE)})`;
  }
  return null;
}

function authHeaders(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** 提取后端 {code,message,data} 的 message(失败提示尽量带后端文案)。 */
async function backendMessage(res: Response, fallback: string): Promise<string> {
  const json = (await res.json().catch(() => null)) as { message?: string } | null;
  return json?.message || fallback;
}

/** 直传单个附件 → 孤儿附件(未关联)。失败 throw(带后端 message)。 */
export async function uploadAttachment(file: File): Promise<AttachmentPublic> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${getApiBase()}/api/v1/attachments`, {
    method: "POST",
    headers: authHeaders(), // 不设 Content-Type,浏览器自带 multipart boundary
    body: fd,
    credentials: "include",
  });
  if (!res.ok) throw new Error(await backendMessage(res, `附件上传失败 (${res.status})`));
  const json = (await res.json().catch(() => null)) as { data?: AttachmentPublic } | null;
  if (!json?.data) throw new Error("附件上传失败:响应异常");
  return json.data;
}

/** 鉴权下载 → 触发浏览器另存(强制 attachment,不在页内预览)。 */
export async function downloadAttachment(id: number, filename: string): Promise<void> {
  const res = await fetch(`${getApiBase()}/api/v1/attachments/${id}/download`, {
    method: "GET",
    headers: authHeaders(),
    credentials: "include",
  });
  if (!res.ok) throw new Error(await backendMessage(res, `下载失败 (${res.status})`));
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** 删除孤儿附件(仅未关联的可删)。 */
export async function deleteAttachment(id: number): Promise<void> {
  const res = await fetch(`${getApiBase()}/api/v1/attachments/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
    credentials: "include",
  });
  if (!res.ok) throw new Error(await backendMessage(res, `删除附件失败 (${res.status})`));
}
