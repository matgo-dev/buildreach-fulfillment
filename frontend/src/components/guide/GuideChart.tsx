"use client";

import { Fragment } from "react";
import { ArrowRightOutlined } from "@ant-design/icons";
import {
  GUIDE_BANDS,
  GUIDE_CATEGORY_META,
  GUIDE_NODES,
  type GuideNode,
  type GuideRole,
} from "@/config/guideFlow";
import { colors } from "@/lib/tokens";
import { GuideNodeCard } from "./GuideNodeCard";

/** 语义域图例:每类一个色条 + 名称。颜色取自 GUIDE_CATEGORY_META 的 token,不另立色板。 */
function CategoryLegend() {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
      {GUIDE_CATEGORY_META.map((m) => (
        <span key={m.id} style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <span
            style={{ width: 4, height: 16, borderRadius: 2, background: colors[m.colorToken] }}
          />
          <span style={{ fontSize: 12, color: colors.muted }}>{m.label}</span>
        </span>
      ))}
    </div>
  );
}

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
      <CategoryLegend />
      {props.showMaster && (
        <section style={{ padding: "12px 16px", borderRadius: 8, background: colors.bg }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: colors.muted, marginBottom: 12 }}>
            开单之前:这些基础资料要先建好
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {GUIDE_NODES.filter((n) => n.layer === "MASTER").map((n) => (
              <GuideNodeCard
                key={n.id}
                node={n}
                dimmed={isDimmed(n)}
                active={activeId === n.id}
                onClick={onNodeClick}
              />
            ))}
          </div>
        </section>
      )}
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
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                    <GuideNodeCard
                      node={n}
                      dimmed={isDimmed(n)}
                      active={activeId === n.id}
                      onClick={onNodeClick}
                    />
                    {props.showMoney && (
                      <MoneyBranch
                        anchorId={n.id}
                        isDimmed={isDimmed}
                        activeId={activeId}
                        onNodeClick={onNodeClick}
                      />
                    )}
                  </div>
                </Fragment>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

/** 取挂在 anchorId 下的资金流链(可能多级:outbound → receivable → receipt)。 */
function moneyChainOf(anchorId: string): GuideNode[] {
  const chain: GuideNode[] = [];
  let cursor = anchorId;
  for (;;) {
    const next = GUIDE_NODES.find((n) => n.layer === "MONEY" && n.anchorId === cursor);
    if (!next) break;
    chain.push(next);
    cursor = next.id;
  }
  return chain;
}

function MoneyBranch({
  anchorId, isDimmed, activeId, onNodeClick,
}: {
  anchorId: string;
  isDimmed: (n: GuideNode) => boolean;
  activeId: string | null;
  onNodeClick: (n: GuideNode) => void;
}) {
  const chain = moneyChainOf(anchorId);
  if (chain.length === 0) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4, marginTop: 8 }}>
      {chain.map((n) => (
        <Fragment key={n.id}>
          <div style={{ fontSize: 12, color: colors.muted, textAlign: "center", lineHeight: 1.3, maxWidth: 148 }}>
            ↓ {n.inEdgeLabel}
          </div>
          <GuideNodeCard node={n} dimmed={isDimmed(n)} active={activeId === n.id} onClick={onNodeClick} />
        </Fragment>
      ))}
    </div>
  );
}

function ChainArrow({ label }: { label?: string }) {
  return (
    <div
      style={{
        display: "flex", flexDirection: "column", alignItems: "center",
        width: 76, gap: 4, marginTop: 24,
      }}
    >
      <div style={{ fontSize: 12, color: colors.muted, textAlign: "center", lineHeight: 1.3 }}>
        {label}
      </div>
      <ArrowRightOutlined style={{ fontSize: 12, color: colors.muted }} />
    </div>
  );
}
