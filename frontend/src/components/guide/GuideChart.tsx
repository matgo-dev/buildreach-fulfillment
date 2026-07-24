"use client";

import { Fragment } from "react";
import { ArrowRightOutlined } from "@ant-design/icons";
import { GUIDE_BANDS, GUIDE_NODES, type GuideNode, type GuideRole } from "@/config/guideFlow";
import { colors } from "@/lib/tokens";
import { GuideNodeCard } from "./GuideNodeCard";

interface Props {
  /** Task 3 起生效:展开资金流支线 */
  showMoney: boolean;
  /** Task 3 起生效:展开链外前置主数据 */
  showMaster: boolean;
  highlightRole: GuideRole | null;
  activeId: string | null;
  onNodeClick: (node: GuideNode) => void;
}

export function GuideChart(props: Props) {
  const { highlightRole, activeId, onNodeClick } = props;
  const isDimmed = (n: GuideNode) => highlightRole !== null && n.role !== highlightRole;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {GUIDE_BANDS.map((band) => {
        const nodes = GUIDE_NODES.filter((n) => n.layer === "MAIN" && n.band === band.id);
        return (
          <section
            key={band.id}
            style={{ padding: "16px 16px 20px", borderRadius: 8, background: colors.bg }}
          >
            <div style={{ fontSize: 12, fontWeight: 600, color: colors.muted, marginBottom: 12 }}>
              {band.title}
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: 8 }}>
              {nodes.map((n, i) => (
                <Fragment key={n.id}>
                  {i > 0 && <ChainArrow label={n.inEdgeLabel} />}
                  <GuideNodeCard
                    node={n}
                    dimmed={isDimmed(n)}
                    active={activeId === n.id}
                    onClick={onNodeClick}
                  />
                </Fragment>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function ChainArrow({ label }: { label?: string }) {
  return (
    <div
      style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        width: 92, gap: 4, marginTop: 24,
      }}
    >
      <div style={{ fontSize: 12, color: colors.muted, textAlign: "center", lineHeight: 1.3 }}>
        {label}
      </div>
      <ArrowRightOutlined style={{ fontSize: 12, color: colors.muted }} />
    </div>
  );
}
