"use client";

import { Fragment } from "react";
import { ArrowRightOutlined, BranchesOutlined } from "@ant-design/icons";
import { Divider, Tag, Tooltip, Typography } from "antd";
import { colors } from "@/lib/tokens";
import { ForwardFlowDraftGuide } from "./ForwardFlowDraftGuide";

type Tone = "doc" | "goods" | "money" | "boundary" | "danger";

interface FlowNode {
  title: string;
  sub: string;
  tone: Tone;
  note?: string;
  tag?: string;
}

interface ReverseScenario {
  title: string;
  range: string;
  entry: string;
  nodes: FlowNode[];
  conclusion: string;
}

const scenarios: ReverseScenario[] = [
  {
    title: "阶段 A:发货/拉货确认前",
    range: "报价单、销售单、采购单阶段;供应商未动货,没有应收/应付事实。",
    entry: "客户取消/退单诉求",
    nodes: [
      { title: "关联报价/销售单", sub: "确认取消范围", tone: "doc" },
      { title: "关闭原正向单据", sub: "状态取消/作废", tone: "doc" },
      { title: "不建逆向单据", sub: "只留原因和审计", tone: "doc" },
    ],
    conclusion: "这一段不是退货退款流程,只是内部单据取消。",
  },
  {
    title: "阶段 B:入库单已创建,货在途",
    range: "供应商已发货或我方已拉货;货未到货代仓;草案中应收/应付已生成。",
    entry: "客户要求取消/退款",
    nodes: [
      { title: "关联销售单", sub: "确认产品/价格/数量", tone: "doc" },
      { title: "订单专员确认供应商", sub: "能否拦截/退回", tone: "boundary" },
      { title: "供应商接受", sub: "在途取消/退回单", tone: "goods" },
      { title: "处理钱", sub: "应收/应付/预收/预付", tone: "money" },
      { title: "关闭原链路", sub: "销售/采购/入库标记完成", tone: "doc" },
    ],
    conclusion: "这是发货后撤回,需要逆向依据单据,但目标仍是结束未完成履约。",
  },
  {
    title: "阶段 C:货到货代仓,未形成出库单",
    range: "确认入库后已有销售单维度库存;还没进入出库单/装柜段。",
    entry: "客户要求取消/退款",
    nodes: [
      { title: "关联销售单", sub: "确认产品/价格/数量", tone: "doc" },
      { title: "确认供应商是否接受", sub: "退回货代仓内货物", tone: "boundary" },
      { title: "供应商接受", sub: "供应商退货单", tone: "goods" },
      { title: "库存减少", sub: "不进入自由库存", tone: "goods" },
      { title: "处理钱", sub: "客户退款/预收 + 供应商冲正", tone: "money" },
    ],
    conclusion: "供应商不接受时分两支:公司不承担则拒绝客户;公司承担则特批退款/费用,但 MVP 不产生自由库存。",
  },
  {
    title: "阶段 D:出库单形成后",
    range: "出库单一旦形成,正向流程终止;可能已装柜、在途或客户已收货。",
    entry: "客户退货/退款诉求",
    nodes: [
      { title: "新建客户退货退款流程", sub: "不回滚原单据", tone: "danger" },
      { title: "关联销售单", sub: "确认产品/价格/数量", tone: "doc" },
      { title: "追溯出库/入库/采购", sub: "只查历史依据", tone: "doc" },
      { title: "供应商确认", sub: "接受/不接受", tone: "boundary" },
      { title: "处理货和钱", sub: "退供应商/退款/预收/费用", tone: "money" },
    ],
    conclusion: "这一段才是独立退货退款流程;原销售、采购、入库、出库单不再关闭或倒回。",
  },
];

const toneMeta: Record<Tone, { color: string; bg: string; border: string; label: string }> = {
  doc: { color: colors.brand, bg: colors.white, border: colors.line, label: "业务单据" },
  goods: { color: colors.info, bg: colors.white, border: colors.line, label: "货 · 实物" },
  money: { color: colors.brandAccent, bg: colors.white, border: colors.line, label: "钱 · 财务" },
  boundary: {
    color: colors.status.warning.dot,
    bg: colors.status.warning.bg,
    border: colors.status.warning.border,
    label: "判断边界",
  },
  danger: {
    color: colors.status.danger.dot,
    bg: colors.status.danger.bg,
    border: colors.status.danger.border,
    label: "终止边界",
  },
};

export function ReverseBoundaryDecisionGuide() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <section style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <Typography.Text strong style={{ color: colors.navy }}>
          正向草案与边界
        </Typography.Text>
        <ForwardFlowDraftGuide compact />
      </section>

      <Divider style={{ margin: "4px 0", borderColor: colors.line }} />

      <section style={{ display: "grid", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <BranchesOutlined style={{ color: colors.brand }} />
          <Typography.Text strong style={{ color: colors.navy }}>
            不同阶段的取消 / 退货 / 退款处理
          </Typography.Text>
        </div>
        {scenarios.map((scenario) => (
          <ScenarioSection key={scenario.title} scenario={scenario} />
        ))}
      </section>
    </div>
  );
}

function ScenarioSection({ scenario }: { scenario: ReverseScenario }) {
  return (
    <section
      style={{
        padding: "16px 16px 20px",
        borderRadius: 8,
        background: colors.bg,
        border: `1px solid ${colors.line}`,
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
        <Typography.Text strong style={{ color: colors.navy }}>
          {scenario.title}
        </Typography.Text>
        <Typography.Text style={{ fontSize: 12, color: colors.muted }}>
          {scenario.range}
        </Typography.Text>
      </div>
      <FlowLine
        nodes={[{ title: scenario.entry, sub: "逆向入口", tone: "boundary" }, ...scenario.nodes]}
      />
      <div
        style={{
          marginTop: 12,
          padding: "8px 10px",
          borderRadius: 8,
          background: colors.white,
          border: `1px solid ${colors.line}`,
          fontSize: 12,
          color: colors.ink,
          lineHeight: 1.5,
        }}
      >
        {scenario.conclusion}
      </div>
    </section>
  );
}

function FlowLine({ nodes }: { nodes: FlowNode[] }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-start", gap: 8 }}>
      {nodes.map((node, index) => (
        <Fragment key={`${node.title}-${index}`}>
          {index > 0 && <ChainArrow />}
          <FlowCard node={node} />
        </Fragment>
      ))}
    </div>
  );
}

function FlowCard({ node }: { node: FlowNode }) {
  const meta = toneMeta[node.tone];
  return (
    <Tooltip title={node.note} mouseEnterDelay={0.3}>
      <div
        style={{
          width: 160,
          minHeight: 92,
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
        <div style={{ display: "flex", justifyContent: "flex-end", minHeight: 22 }}>
          {node.tag && (
            <Tag color={node.tone === "danger" ? "error" : "warning"} style={{ marginInlineEnd: 0, fontSize: 11 }}>
              {node.tag}
            </Tag>
          )}
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, lineHeight: 1.35, color: colors.ink }}>
          {node.title}
        </div>
        <div style={{ fontSize: 12, color: colors.muted, marginTop: 4, lineHeight: 1.35 }}>
          {node.sub}
        </div>
      </div>
    </Tooltip>
  );
}

function ChainArrow() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: 32,
        marginTop: 36,
      }}
    >
      <ArrowRightOutlined style={{ fontSize: 12, color: colors.muted }} />
    </div>
  );
}
