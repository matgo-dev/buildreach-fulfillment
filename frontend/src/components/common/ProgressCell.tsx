"use client";
import { colors } from "@/lib/tokens";

/**
 * 派生「覆盖进度」的统一可视化(与 StatusTag 平级、互补的单一源头)。
 *
 * 为什么和 StatusTag 分家:列表里「单据状态」(生命周期状态机)与「收货/采购进度」(派生覆盖度)
 * 是两条正交轴,若都渲染成同形同色的实心 pill,不熟系统的人分不清"谁是谁"。故进度**换形态**——
 * 描边 chip + 分级方块图标(空 / 半 / 实),一眼读作「覆盖进度」而非「又一个状态」。
 *
 * 有意**不用连续进度条**:列级只有三态(未 / 部分 / 已全部),没有精确"已收/总"分数,
 * 连续条会谎报精度(半满条被误读成"收了 50%")。分级方块只表"未开始 / 进行中 / 完成"三档,诚实不越权。
 * 三态由 color 判级:default=未开始 / processing=进行中 / success=完成(与各进度枚举单一源头一致)。
 */
export interface ProgressMeta {
  label: string;
  color: string;
}

// 语义色 → 图标色(取 tokens 单一源头,不写裸 hex)。
const TONE: Record<string, string> = {
  success: colors.success,
  processing: colors.info,
  default: colors.muted,
};

/** 分级方块:未开始=空心描边 / 进行中=左半填充 / 完成=实心。非连续条,不表精确比例。 */
function StateGlyph({ level, tone }: { level: "none" | "partial" | "full"; tone: string }) {
  const base = { width: 11, height: 11, borderRadius: 2, flex: "0 0 auto" as const };
  if (level === "full") return <span style={{ ...base, background: tone }} />;
  if (level === "partial")
    return (
      <span
        style={{
          ...base,
          border: `1.5px solid ${tone}`,
          background: `linear-gradient(90deg, ${tone} 50%, transparent 50%)`,
        }}
      />
    );
  return <span style={{ ...base, border: `1.5px solid ${tone}` }} />;
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
  const tone = TONE[m.color] ?? colors.muted;
  const level = m.color === "success" ? "full" : m.color === "processing" ? "partial" : "none";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        border: `1px solid ${colors.line}`,
        borderRadius: 999,
        padding: "1px 8px",
        fontSize: 12,
        lineHeight: "18px",
        color: colors.ink,
        background: colors.white,
        whiteSpace: "nowrap",
      }}
    >
      <StateGlyph level={level} tone={tone} />
      {m.label}
    </span>
  );
}
