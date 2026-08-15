"use client";

import { Fragment } from "react";
import { ArrowRightOutlined, ExclamationCircleOutlined } from "@ant-design/icons";
import { Tag, Tooltip, Typography } from "antd";
import {
  DRAFT_FLOW_BANDS,
  DRAFT_MONEY_BRANCHES,
  DRAFT_FLOW_NODES,
  type DraftFlowCategory,
  type DraftMoneyBranch,
  type DraftFlowNode,
} from "@/config/forwardFlowDraft";
import { colors } from "@/lib/tokens";
import { GUIDE_ICONS } from "./guideIcons";

const CATEGORY_META: Record<
  DraftFlowCategory,
  { label: string; color: string; bg: string; border: string }
> = {
  DOCUMENT: { label: "业务单据", color: colors.brand, bg: colors.white, border: colors.line },
  GOODS: { label: "货 · 实物", color: colors.info, bg: colors.white, border: colors.line },
  MONEY: { label: "钱 · 财务", color: colors.brandAccent, bg: colors.white, border: colors.line },
  BOUNDARY: {
    label: "关键边界",
    color: colors.status.warning.dot,
    bg: colors.status.warning.bg,
    border: colors.status.warning.border,
  },
};

export function ForwardFlowDraftGuide({ compact = false }: { compact?: boolean }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {!compact && (
        <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
          这是一版正向流程草案图:把“供应商发货/我方拉货确认”放到入库单创建处,供应商应付在这个点成立;
          确认入库只产生库存,客户应收仍在确认出库时产生。用于讨论,暂不代表已落库规则。
        </Typography.Paragraph>
      )}

      <Legend />

      <section
        style={{
          padding: 16,
          borderRadius: 8,
          background: colors.status.warning.bg,
          border: `1px solid ${colors.status.warning.border}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <ExclamationCircleOutlined style={{ color: colors.status.warning.text }} />
          <Typography.Text strong style={{ color: colors.navy }}>
            本版草案的两个判断点
          </Typography.Text>
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          <BoundaryPill
            label="边界一:确认发货/拉货"
            text="在这之前只有报价、销售、采购等内部履约单据变化,不涉及供应商应付和库存事实,通常可以做状态取消/回退;客户预收如存在,作为独立财务事项处理。"
          />
          <BoundaryPill
            label="入库单创建之后"
            text="如果供应商应付在这里生成,后续再撤回就不能只是改状态,需要用逆向依据单据处理应付、预付、退款、核销或冲正;客户预收可独立处理,客户应收仍等确认出库。"
          />
          <BoundaryPill
            label="边界二:出库单形成"
            text="这以后原正向流程终止,不再回退原单据;客户退货退款要新建独立逆向流程,只关联原销售单确认产品、价格和数量。"
          />
        </div>
      </section>

      {DRAFT_FLOW_BANDS.map((band) => {
        const nodes = DRAFT_FLOW_NODES.filter((n) => n.band === band.id);
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
                    <DraftNodeCard node={n} />
                    <MoneyBranches anchorId={n.id} />
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

function Legend() {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
      {(Object.keys(CATEGORY_META) as DraftFlowCategory[]).map((key) => {
        const meta = CATEGORY_META[key];
        return (
          <span key={key} style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <span style={{ width: 4, height: 16, borderRadius: 2, background: meta.color }} />
            <span style={{ fontSize: 12, color: colors.muted }}>{meta.label}</span>
          </span>
        );
      })}
    </div>
  );
}

function BoundaryPill({ label, text }: { label: string; text: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        padding: "8px 10px",
        borderRadius: 8,
        background: colors.white,
        border: `1px solid ${colors.status.warning.border}`,
      }}
    >
      <Typography.Text strong style={{ fontSize: 12, color: colors.status.warning.text }}>
        {label}
      </Typography.Text>
      <Typography.Text style={{ fontSize: 12, color: colors.ink }}>{text}</Typography.Text>
    </div>
  );
}

function MoneyBranches({ anchorId }: { anchorId: string }) {
  const branches = DRAFT_MONEY_BRANCHES.filter((n) => n.anchorId === anchorId);
  if (branches.length === 0) return null;
  const edgeLabel =
    branches.length === 1
      ? branches[0].inEdgeLabel
      : Array.from(new Set(branches.map((branch) => branch.inEdgeLabel))).join(" / ");
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, marginTop: 8 }}>
      <div style={{ fontSize: 12, color: colors.status.warning.text, textAlign: "center", lineHeight: 1.3 }}>
        ↓ {edgeLabel}
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "center" }}>
        {branches.map((node) => (
          <MoneyNodeCard key={node.id} node={node} />
        ))}
      </div>
    </div>
  );
}

function MoneyNodeCard({ node }: { node: DraftMoneyBranch }) {
  return (
    <Tooltip title={node.note} mouseEnterDelay={0.3}>
      <div
        style={{
          width: 152,
          minHeight: 78,
          padding: "8px 12px",
          textAlign: "left",
          borderRadius: 8,
          background: colors.white,
          borderTop: `1px solid ${colors.line}`,
          borderRight: `1px solid ${colors.line}`,
          borderBottom: `1px solid ${colors.line}`,
          borderLeft: `4px solid ${colors.brandAccent}`,
        }}
      >
        <div style={{ fontSize: 16, lineHeight: 1, marginBottom: 8, color: colors.brand }}>
          {GUIDE_ICONS[node.iconKey]}
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.35, color: colors.ink }}>
          {node.action}
        </div>
        <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>{node.docName}</div>
        <div style={{ fontSize: 11, color: colors.muted, lineHeight: 1.3, marginTop: 8 }}>
          {node.settlement}
        </div>
      </div>
    </Tooltip>
  );
}

function DraftNodeCard({ node }: { node: DraftFlowNode }) {
  const meta = CATEGORY_META[node.category];
  return (
    <Tooltip title={node.note} mouseEnterDelay={0.3}>
      <div
        style={{
          width: 168,
          minHeight: 96,
          padding: "8px 12px",
          textAlign: "left",
          borderRadius: 8,
          background: meta.bg,
          borderTop: `1px solid ${meta.border}`,
          borderRight: `1px solid ${meta.border}`,
          borderBottom: `1px solid ${meta.border}`,
          borderLeft: `4px solid ${meta.color}`,
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 8 }}>
          <span style={{ fontSize: 16, lineHeight: 1, color: colors.brand }}>
            {GUIDE_ICONS[node.iconKey]}
          </span>
          {node.boundary && (
            <Tag color="warning" style={{ marginInlineEnd: 0, fontSize: 11 }}>
              边界
            </Tag>
          )}
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.35, color: colors.ink }}>
          {node.action}
        </div>
        <div style={{ fontSize: 12, color: colors.muted, marginTop: 4 }}>{node.docName}</div>
        {node.sideEffects && (
          <div style={{ display: "flex", flexDirection: "column", gap: 2, marginTop: 8 }}>
            {node.sideEffects.map((item) => (
              <span key={item} style={{ fontSize: 11, color: colors.muted, lineHeight: 1.25 }}>
                {item}
              </span>
            ))}
          </div>
        )}
      </div>
    </Tooltip>
  );
}

function ChainArrow({ label }: { label?: string }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: 76,
        gap: 4,
        marginTop: 26,
      }}
    >
      <div style={{ fontSize: 12, color: colors.muted, textAlign: "center", lineHeight: 1.3 }}>
        {label}
      </div>
      <ArrowRightOutlined style={{ fontSize: 12, color: colors.muted }} />
    </div>
  );
}
