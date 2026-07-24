"use client";

import { Tooltip } from "antd";
import { GUIDE_CATEGORY_META, nodeCategory, type GuideNode } from "@/config/guideFlow";
import { colors } from "@/lib/tokens";
import { GUIDE_ICONS } from "./guideIcons";

/** 分类 → 左边色条颜色。取自 GUIDE_CATEGORY_META 的 colorToken,不另立色板。 */
function categoryColor(node: GuideNode): string {
  const meta = GUIDE_CATEGORY_META.find((m) => m.id === nodeCategory(node));
  return colors[meta?.colorToken ?? "muted"];
}

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
        id={`guide-node-${node.id}`}
        onClick={() => onClick?.(node)}
        style={{
          width: 148,
          minHeight: 76,
          padding: "8px 12px",
          textAlign: "left",
          borderRadius: 8,
          cursor: "pointer",
          background: isMaster ? colors.bg : colors.white,
          // 四条边全用长写,不用 border 简写 —— 简写会重置四边,active 切换时
          // React 只重写变化的 border 而不重写未变的 borderLeft,分类左色条会被抹掉。
          borderTop: `1px solid ${active ? colors.brand : colors.line}`,
          borderRight: `1px solid ${active ? colors.brand : colors.line}`,
          borderBottom: `1px solid ${active ? colors.brand : colors.line}`,
          borderLeft: `4px solid ${categoryColor(node)}`,
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
