// 商品状态机的前端镜像 —— 唯一权威源头是 backend db/models/spu.py SpuStatus(转移/可编辑/可删)。
// 此处只把它映射成 UI 呈现(标签色 + 按钮显隐),不重复定义业务规则:后端才是硬约束,
// 前端隐藏按钮只是 UX,越权调用仍被后端 409 拦。语义 = 能否被下游(报价)选用,非对外可见。
import type { ProductStatus } from "@/lib/catalog";

/** SPU 三态:草稿(录入中)/ 启用(可被报价选用)/ 停用(淘汰,留历史)。 */
export const SPU_STATUS_META: Record<ProductStatus, { label: string; color: string }> = {
  DRAFT: { label: "草稿", color: "gold" },
  ACTIVE: { label: "启用", color: "success" },
  INACTIVE: { label: "停用", color: "default" },
};

/** 镜像 SpuStatus.EDITABLE / DELETABLE:仅 DRAFT / INACTIVE 可改可删;ACTIVE 锁(先停用)。 */
export const spuEditable = (s: ProductStatus): boolean => s !== "ACTIVE";
export const spuDeletable = (s: ProductStatus): boolean => s !== "ACTIVE";

/** 镜像转移白名单的"下一步":ACTIVE→停用;DRAFT/INACTIVE→启用(启用会过后端完备性校验)。 */
export function spuNextAction(s: ProductStatus): { to: ProductStatus; label: string } {
  return s === "ACTIVE" ? { to: "INACTIVE", label: "停用" } : { to: "ACTIVE", label: "启用" };
}

/** SKU 二态(变体在售/停售)。SKU 上下架豁免父 SPU 锁,故不含 editable 判断。 */
export const SKU_STATUS_META: Record<string, { label: string; color: string }> = {
  ACTIVE: { label: "在售", color: "success" },
  INACTIVE: { label: "停售", color: "default" },
};
export const skuNextActionLabel = (s: string): string => (s === "ACTIVE" ? "停售" : "恢复在售");
