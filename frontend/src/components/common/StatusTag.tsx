"use client";
import { Tag } from "antd";
import { colors } from "@/lib/tokens";

/** 各域 *_STATUS_META / *_PROGRESS_META 的统一元数据形状(数据保持分域,不合并)。 */
export interface StatusMeta {
  label: string;
  color: string;
}

const TONE_ALIAS = {
  success: "success",
  processing: "info",
  info: "info",
  warning: "warning",
  default: "neutral",
  neutral: "neutral",
  error: "danger",
  danger: "danger",
} as const;

type StatusTone = keyof typeof colors.status;
type StatusToneAlias = keyof typeof TONE_ALIAS;

function resolveTone(color: string | undefined): StatusTone {
  if (!color) return "neutral";
  return TONE_ALIAS[color as StatusToneAlias] ?? "neutral";
}

/**
 * 状态徽标:业务域只传语义名,组件统一落 DESIGN.md §1.3 的精确色 + 圆点。
 * value 不在 meta 时兜底:显 value 原文 + 中性状态色。
 */
export function StatusTag({
  meta,
  value,
}: {
  meta: Record<string, StatusMeta>;
  value: string;
}) {
  const m = meta[value] as StatusMeta | undefined;
  const tone = colors.status[resolveTone(m?.color)];
  return (
    <Tag
      bordered
      style={{
        alignItems: "center",
        background: tone.bg,
        borderColor: tone.border,
        borderRadius: 999,
        color: tone.text,
        display: "inline-flex",
        fontSize: 11,
        fontWeight: 500,
        gap: 6,
        lineHeight: "18px",
        marginInlineEnd: 0,
        paddingInline: 8,
      }}
    >
      <span
        aria-hidden="true"
        style={{
          background: tone.dot,
          borderRadius: "50%",
          display: "inline-block",
          height: 6,
          width: 6,
        }}
      />
      <span>{m?.label ?? value}</span>
    </Tag>
  );
}
