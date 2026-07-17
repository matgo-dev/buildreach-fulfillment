"use client";
import { Tag } from "antd";

/** 各域 *_STATUS_META / *_PROGRESS_META 的统一元数据形状(数据保持分域,不合并)。 */
export interface StatusMeta {
  label: string;
  color: string;
}

/**
 * 状态徽标:统一渲染 `<Tag color={META[v].color}>{META[v].label}</Tag>` 同构结构。
 * value 不在 meta 时兜底:显 value 原文 + AntD 默认色(与既有 `META[v]?.label ?? v` 行为一致;
 * 全键 Record 域则永远命中,行为不变)。
 */
export function StatusTag({
  meta,
  value,
}: {
  meta: Record<string, StatusMeta>;
  value: string;
}) {
  const m = meta[value] as StatusMeta | undefined;
  return <Tag color={m?.color}>{m?.label ?? value}</Tag>;
}
