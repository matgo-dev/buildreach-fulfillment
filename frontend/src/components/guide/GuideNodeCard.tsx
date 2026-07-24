"use client";

import { Tooltip } from "antd";
import type { GuideNode } from "@/config/guideFlow";
import { colors } from "@/lib/tokens";
import { GUIDE_ICONS } from "./guideIcons";

interface Props {
  node: GuideNode;
  /** 角色筛选未命中 → 淡化(不隐藏,新人要看见上下游) */
  dimmed?: boolean;
  /** 「跟一单货走一遍」当前步 → 点亮 */
  active?: boolean;
  onClick?: (node: GuideNode) => void;
}

export function GuideNodeCard({ node, dimmed, active, onClick }: Props) {
  const isMaster = node.layer === "MASTER";
  return (
    <Tooltip title={node.tooltip} mouseEnterDelay={0.3}>
      <button
        type="button"
        onClick={() => onClick?.(node)}
        style={{
          width: 148,
          minHeight: 76,
          padding: "8px 12px",
          textAlign: "left",
          borderRadius: 8,
          cursor: "pointer",
          background: isMaster ? colors.bg : colors.white,
          border: `1px solid ${active ? colors.brand : colors.line}`,
          boxShadow: active ? `0 0 0 4px ${colors.brand}22` : "none",
          opacity: dimmed ? 0.3 : 1,
          transition: "opacity .2s, box-shadow .2s, border-color .2s",
        }}
      >
        <div style={{ fontSize: 16, lineHeight: 1, marginBottom: 8, color: colors.brand }}>
          {GUIDE_ICONS[node.iconKey]}
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.35, color: colors.ink }}>
          {node.action}
        </div>
        <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>{node.docName}</div>
      </button>
    </Tooltip>
  );
}
