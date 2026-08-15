"use client";

import { useEffect, useState } from "react";
import { Checkbox, Segmented, Space, Typography } from "antd";
import { ForwardFlowDraftGuide } from "@/components/guide/ForwardFlowDraftGuide";
import { GuideChart } from "@/components/guide/GuideChart";
import { GuideDrawer } from "@/components/guide/GuideDrawer";
import { GuideTour } from "@/components/guide/GuideTour";
import { ReverseFlowGuide } from "@/components/guide/ReverseFlowGuide";
import { ReverseBoundaryDecisionGuide } from "@/components/guide/ReverseBoundaryDecisionGuide";
import { GUIDE_NODES, GUIDE_ROLE_OPTIONS, TOUR_SEQUENCE, guideNodeById } from "@/config/guideFlow";
import type { GuideNode, GuideRole } from "@/config/guideFlow";
import { colors } from "@/lib/tokens";

type GuideTabKey = "forward" | "forward-draft" | "reverse-boundary" | "reverse";

const GUIDE_TABS: { key: GuideTabKey; label: string }[] = [
  { key: "forward", label: "正向流程" },
  { key: "forward-draft", label: "正向草案" },
  { key: "reverse-boundary", label: "退货边界确认" },
  { key: "reverse", label: "逆向/撤销" },
];

export default function GuidePage() {
  const [activeTab, setActiveTab] = useState<GuideTabKey>("forward");
  const [activeNode, setActiveNode] = useState<GuideNode | null>(null);
  const [highlightRole, setHighlightRole] = useState<GuideRole | null>(null);
  const [showMoney, setShowMoney] = useState(false);
  const [showMaster, setShowMaster] = useState(false);
  const [tourStep, setTourStep] = useState<number | null>(null);

  const tourNodeId = tourStep === null ? null : TOUR_SEQUENCE[tourStep];

  // 叙事走到资金流节点时自动展开资金流层,否则该节点不在 DOM 里,点亮不到。
  useEffect(() => {
    if (tourNodeId && guideNodeById(tourNodeId)?.layer === "MONEY") setShowMoney(true);
  }, [tourNodeId]);

  // 叙事推进时把当前节点滚动到可见 —— 否则点亮的节点可能在视口外,看着像没反应。
  // 依赖 showMoney/showMaster:折叠层刚被上一个 effect 展开后,节点才进 DOM,这里才滚得到。
  useEffect(() => {
    if (!tourNodeId) return;
    document
      .getElementById(`guide-node-${tourNodeId}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [tourNodeId, showMoney, showMaster]);

  // 选中的岗位如果全部节点都不在主链层,说明它挂在某个默认折叠的支线层上,
  // 不展开就整图全灰、点不亮任何节点。只做展开,不自动收起用户已打开的层。
  useEffect(() => {
    if (!highlightRole) return;
    const roleNodes = GUIDE_NODES.filter((n) => n.role === highlightRole);
    if (roleNodes.some((n) => n.layer === "MAIN")) return;
    if (roleNodes.some((n) => n.layer === "MONEY")) setShowMoney(true);
    if (roleNodes.some((n) => n.layer === "MASTER")) setShowMaster(true);
  }, [highlightRole]);

  // 开始叙事先清角色筛选:否则非该角色节点被淡化,叙事点亮它们时会打架。
  const startTour = () => {
    setActiveTab("forward");
    setHighlightRole(null);
    setTourStep(0);
  };
  const exitTour = () => setTourStep(null);
  const switchTab = (key: GuideTabKey) => {
    setActiveTab(key);
    setTourStep(null);
    setActiveNode(null);
  };

  return (
    <div style={{ padding: 24, maxWidth: 1400 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          平台导览
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>
          一单货从接到客户询价,到最后收清货款,在这个平台里要经过下面这些步骤。点任意一步看详细说明。
        </Typography.Paragraph>

        <div role="tablist" aria-label="平台导览视图" style={{ display: "flex", gap: 28, borderBottom: `1px solid ${colors.line}`, marginBottom: 16 }}>
          {GUIDE_TABS.map((tab) => {
            const active = tab.key === activeTab;
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => switchTab(tab.key)}
                style={{
                  appearance: "none",
                  border: 0,
                  borderBottom: `2px solid ${active ? colors.brand : "transparent"}`,
                  background: "transparent",
                  color: active ? colors.brand : colors.muted,
                  cursor: "pointer",
                  font: "inherit",
                  fontWeight: active ? 600 : 400,
                  padding: "12px 0",
                }}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {activeTab === "forward" && (
          <>
            <div style={{ marginBottom: 16 }}>
              <Space size={20} style={{ marginBottom: 12 }}>
                <Checkbox checked={showMoney} onChange={(e) => setShowMoney(e.target.checked)}>
                  看钱怎么走
                </Checkbox>
                <Checkbox checked={showMaster} onChange={(e) => setShowMaster(e.target.checked)}>
                  看基础资料从哪来
                </Checkbox>
              </Space>
              <div>
                <Typography.Text type="secondary" style={{ fontSize: 12, display: "block", marginBottom: 8 }}>
                  按岗位看:选一个岗位,和它相关的步骤会亮起来,其余变淡(不隐藏 —— 你需要知道自己这步的上下游是谁)。
                </Typography.Text>
                <Segmented
                  value={highlightRole ?? "ALL"}
                  onChange={(v) => setHighlightRole(v === "ALL" ? null : (v as GuideRole))}
                  options={[{ value: "ALL", label: "全部" }, ...GUIDE_ROLE_OPTIONS]}
                />
              </div>
            </div>

            <GuideTour
              stepIndex={tourStep}
              onStart={startTour}
              onPrev={() => setTourStep((s) => (s === null ? s : Math.max(0, s - 1)))}
              onNext={() => setTourStep((s) => (s === null ? s : Math.min(TOUR_SEQUENCE.length - 1, s + 1)))}
              onExit={exitTour}
            />

            <GuideChart
              showMoney={showMoney}
              showMaster={showMaster}
              highlightRole={highlightRole}
              activeId={tourNodeId ?? activeNode?.id ?? null}
              onNodeClick={setActiveNode}
            />
            <GuideDrawer node={activeNode} onClose={() => setActiveNode(null)} />
          </>
        )}
        {activeTab === "forward-draft" && <ForwardFlowDraftGuide />}
        {activeTab === "reverse-boundary" && <ReverseBoundaryDecisionGuide />}
        {activeTab === "reverse" && <ReverseFlowGuide />}
    </div>
  );
}
