"use client";
import { colors } from "@/lib/tokens";
import { StatusTag } from "@/components/common/StatusTag";

/**
 * 派生「覆盖进度」的统一渲染入口。
 * 进度与单据状态语义不同,但都属于状态徽标;视觉统一交给 StatusTag 的 DESIGN §1.3 精确色和圆点规则。
 */
export interface ProgressMeta {
  label: string;
  color: string;
}

export function ProgressCell({
  meta,
  value,
}: {
  meta: Record<string, ProgressMeta>;
  value: string;
}) {
  const m = meta[value];
  if (!m) return <span style={{ color: colors.muted }}>—</span>;
  return <StatusTag meta={meta} value={value} />;
}
