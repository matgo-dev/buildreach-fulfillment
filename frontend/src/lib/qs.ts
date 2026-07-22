/** 查询串构建单一实现(收敛自各 lib 文件的同名私有副本):
 *  跳过 undefined / null / 空串;有参则带 `?` 前缀。 */
export function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}
