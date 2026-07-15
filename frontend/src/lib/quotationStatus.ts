// 报价状态机的前端镜像 —— 唯一权威源头是 backend db/models/quotation.py
// (QUOTATION_TRANSITIONS / EDITABLE / DELETABLE / VOIDABLE)。此处只映射 UI 呈现,
// 不重复定义业务规则:后端才是硬约束,前端隐藏按钮只是 UX,越权调用仍被后端拦。
import type { QuotationStatus } from "@/lib/quotation";

/** 四态:草稿(可编辑)/ 锁档(冻结基准)/ 已转销售(终态)/ 已作废(终态)。 */
export const QUOTATION_STATUS_META: Record<QuotationStatus, { label: string; color: string }> = {
  DRAFT: { label: "草稿", color: "default" },
  LOCKED: { label: "锁档", color: "processing" },
  CONVERTED: { label: "已转销售", color: "success" },
  VOID: { label: "已作废", color: "error" },
};

/** 镜像 QUOTATION_EDITABLE / DELETABLE:仅草稿可改可硬删(锁档后只读)。 */
export const quotationEditable = (s: QuotationStatus): boolean => s === "DRAFT";
export const quotationDeletable = (s: QuotationStatus): boolean => s === "DRAFT";

/** 镜像可作废集(草稿/锁档,未转销售前)。 */
export const quotationVoidable = (s: QuotationStatus): boolean => s === "DRAFT" || s === "LOCKED";

/** 详情页状态门禁动作(镜像转移矩阵):锁档=草稿→锁;解锁=锁→草稿;转销售=锁档→已转。 */
export const quotationLockable = (s: QuotationStatus): boolean => s === "DRAFT";
export const quotationUnlockable = (s: QuotationStatus): boolean => s === "LOCKED";
export const quotationConvertible = (s: QuotationStatus): boolean => s === "LOCKED";
