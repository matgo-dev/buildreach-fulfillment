"use client";

import { Fragment } from "react";
import { ArrowRightOutlined, BranchesOutlined } from "@ant-design/icons";
import { Tag, Tooltip, Typography } from "antd";
import { colors } from "@/lib/tokens";

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
  branches?: ScenarioBranch[];
}

interface ScenarioBranch {
  title: string;
  tone: Tone;
  points: string[];
}

const scenarios: ReverseScenario[] = [
  {
    title: "阶段 A:发货/拉货确认前",
    range: "报价单、销售单、采购单阶段;供应商未动货,没有供应商应付事实。客户预收如已发生,作为独立收款事实处理,不驱动履约节点。",
    entry: "客户取消/退单诉求",
    nodes: [
      { title: "关联报价/销售单", sub: "确认取消范围", tone: "doc" },
      { title: "关闭原正向单据", sub: "状态取消/作废", tone: "doc" },
      { title: "不建履约逆向单据", sub: "预收另行处理", tone: "doc" },
    ],
    conclusion: "这一段不是退货退款流程,只是内部履约单据取消;如果已有客户预收,按独立收款/退款规则处理。",
  },
  {
    title: "阶段 B:发货/拉货确认后,出库单形成前",
    range: "入库单已创建,供应商应付已生成;客户应收仍未生成。核心分叉是货是否已到货代仓并确认入库产生库存。",
    entry: "客户要求取消/退款",
    nodes: [
      { title: "关联销售单", sub: "确认产品/价格/数量", tone: "doc" },
      { title: "向供应商确认", sub: "是否接受退回/拦截", tone: "boundary" },
      { title: "按供应商确认结果处理", sub: "接受 / 不接受", tone: "boundary" },
      { title: "再看货到哪儿", sub: "未到仓 / 已入仓", tone: "goods" },
      { title: "处理钱", sub: "费用/冲销/退款", tone: "money" },
      { title: "落原链路状态", sub: "关闭/继续/待处置", tone: "doc" },
    ],
    conclusion: "这一段先向供应商确认接受/不接受,再按货是否已到仓决定是否处理库存;客户侧钱、供应商侧钱的处理口径基本共用。",
    branches: [
      {
        title: "实物分支:货未到货代仓",
        tone: "goods",
        points: [
          "系统尚未形成库存,不做库存扣减或库存归属调整。",
          "供应商接受:创建在途取消/供应商退货单,货在途中拦截或退回供应商。",
          "供应商不接受且公司不承担:退货退款申请驳回/关闭,原正向链路继续。",
          "供应商不接受但公司承担:发起特批,创建费用/损失单;货后续仍按原链路到仓。",
        ],
      },
      {
        title: "实物分支:货已到货代仓,已确认入库并产生库存",
        tone: "goods",
        points: [
          "系统已形成销售单维度库存,必须先处理库存归属。",
          "供应商接受:创建供应商退货单,库存从销售单维度库存扣减并退回供应商。",
          "供应商不接受且公司不承担:驳回客户退货退款,库存继续绑定原销售单,原正向链路继续。",
          "供应商不接受但公司承担:库存不能直接转自由库存,暂挂原销售单或进入待处置状态,后续处置口径待确认。",
        ],
      },
      {
        title: "财务分支:按供应商确认结果处理",
        tone: "money",
        points: [
          "供应商接受:客户侧如有预收则退款/预收退回,无预收则不做应收冲销;供应商侧冲销应付/供应商退款或预付退回。",
          "供应商不接受且公司不承担:不产生客户退款,原供应商应付继续按原链路处理。",
          "供应商不接受但公司承担:客户侧如有预收则退款/预收退回,供应商侧应付不冲正,差额形成公司费用/损失。",
          "以上财务单据均需关联原销售单、采购单、入库单及对应逆向申请。",
        ],
      },
    ],
  },
  {
    title: "阶段 C:出库单形成后",
    range: "出库单一旦形成,正向流程终止;可能已装柜、在途或客户已收货。",
    entry: "客户退货/退款诉求",
    nodes: [
      { title: "新建客户退货退款流程", sub: "不回滚原单据", tone: "danger" },
      { title: "关联销售单", sub: "确认产品/价格/数量", tone: "doc" },
      { title: "追溯出库/入库/采购", sub: "只查历史依据", tone: "doc" },
      { title: "向供应商确认", sub: "接受/不接受", tone: "boundary" },
      { title: "处理货和钱", sub: "退供应商/退款/费用", tone: "money" },
    ],
    conclusion: "这一段才是独立退货退款流程;原销售、采购、入库、出库单不再关闭或倒回。",
    branches: [
      {
        title: "供应商接受",
        tone: "goods",
        points: [
          "创建客户退货退款流程,并衍生供应商退货/换货单。",
          "客户退回货不进入自由库存;按供应商退货/换货结果处理实物。",
          "客户侧:退款、预收退回或应收冲销按审批执行。",
          "供应商侧:供应商退款、应付冲销或换货补发按业务单执行。",
        ],
      },
      {
        title: "供应商不接受",
        tone: "money",
        points: [
          "若公司不承担:客户退货退款申请驳回/关闭,只保留沟通和审批记录。",
          "若公司承担:创建费用/赔付/退款审批,关联原销售单和出库单。",
          "客户侧:退款或应收冲销形成公司费用。",
          "供应商侧:不产生供应商退款/应付冲正;相关采购成本由公司承担。",
        ],
      },
    ],
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
      {scenario.branches && <BranchGrid branches={scenario.branches} />}
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

function BranchGrid({ branches }: { branches: ScenarioBranch[] }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
        gap: 10,
        marginTop: 12,
      }}
    >
      {branches.map((branch) => (
        <BranchCard key={branch.title} branch={branch} />
      ))}
    </div>
  );
}

function BranchCard({ branch }: { branch: ScenarioBranch }) {
  const meta = toneMeta[branch.tone];
  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 8,
        background: colors.white,
        borderTop: `1px solid ${meta.border}`,
        borderRight: `1px solid ${meta.border}`,
        borderBottom: `1px solid ${meta.border}`,
        borderLeft: `4px solid ${meta.color}`,
      }}
    >
      <Typography.Text strong style={{ color: colors.ink, fontSize: 13 }}>
        {branch.title}
      </Typography.Text>
      <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
        {branch.points.map((point) => (
          <Typography.Text key={point} style={{ color: colors.muted, fontSize: 12, lineHeight: 1.55 }}>
            {point}
          </Typography.Text>
        ))}
      </div>
    </div>
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
