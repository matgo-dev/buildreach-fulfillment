"use client";

import { Alert, Tag, Typography } from "antd";
import {
  REVERSE_FLOW_BOUNDARIES,
  REVERSE_FLOW_PRINCIPLES,
  REVERSE_FLOW_TREES,
  type ReverseSeverity,
  type ReverseStep,
} from "@/config/reverseFlow";
import { colors } from "@/lib/tokens";

const { Paragraph, Text } = Typography;

const SEVERITY_META: Record<ReverseSeverity, { label: string; color: string; bg: string }> = {
  normal: { label: "单据", color: colors.status.info.text, bg: colors.status.info.bg },
  goods: { label: "库存", color: colors.status.success.text, bg: colors.status.success.bg },
  money: { label: "账款", color: colors.status.warning.text, bg: colors.status.warning.bg },
  external: { label: "外部资料", color: colors.status.neutral.text, bg: colors.status.neutral.bg },
};

export function ReverseFlowGuide() {
  return (
    <div style={{ display: "grid", gap: 16 }}>
      <Alert
        type="info"
        showIcon
        title="逆向/撤销不是自动级联"
        description="当前平台采用受控撤销:系统在每个写入口做最终守卫,操作者按下游到上游的顺序逐步处理。"
      />

      <section style={{ padding: "16px 18px", background: colors.bg, borderRadius: 8 }}>
        <Text strong>总原则</Text>
        <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
          {REVERSE_FLOW_PRINCIPLES.map((item) => (
            <div key={item} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <span style={{ color: colors.brand, fontWeight: 700 }}>•</span>
              <span style={{ color: colors.ink }}>{item}</span>
            </div>
          ))}
        </div>
      </section>

      <section style={{ padding: "16px 18px", background: colors.bg, borderRadius: 8 }}>
        <Text strong>依赖图</Text>
        <div style={{ display: "grid", gap: 12, marginTop: 12 }}>
          {REVERSE_FLOW_TREES.map((step) => (
            <ReverseStepNode key={step.id} step={step} depth={0} />
          ))}
        </div>
      </section>

      <section style={{ padding: "16px 18px", background: colors.bg, borderRadius: 8 }}>
        <Text strong>还没有定的边界</Text>
        <Paragraph type="secondary" style={{ marginTop: 8, marginBottom: 12 }}>
          下面这些不在当前基础逆向链路里,需要确认业务规则后再开发。
        </Paragraph>
        <div style={{ display: "grid", gap: 8 }}>
          {REVERSE_FLOW_BOUNDARIES.map((item) => (
            <div key={item} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
              <span style={{ color: colors.status.warning.dot, fontWeight: 700 }}>•</span>
              <span style={{ color: colors.ink }}>{item}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function ReverseStepNode({ step, depth }: { step: ReverseStep; depth: number }) {
  const meta = SEVERITY_META[step.severity];
  return (
    <div
      style={{
        marginLeft: depth === 0 ? 0 : 24,
        paddingLeft: depth === 0 ? 0 : 16,
        borderLeft: depth === 0 ? "none" : `1px solid ${colors.line}`,
      }}
    >
      <div
        style={{
          background: colors.white,
          border: `1px solid ${colors.line}`,
          borderLeft: `4px solid ${meta.color}`,
          borderRadius: 8,
          padding: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <Text strong>{step.title}</Text>
          <Tag
            style={{
              marginInlineEnd: 0,
              color: meta.color,
              background: meta.bg,
              borderColor: colors.line,
            }}
          >
            {meta.label}
          </Tag>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {step.owner}
          </Text>
        </div>
        <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
          <Line label="什么时候" text={step.when} />
          <Line label="系统结果" text={step.result} />
          {step.blocks ? <Line label="挡住时" text={step.blocks} danger /> : null}
        </div>
      </div>
      {step.children && step.children.length > 0 ? (
        <div style={{ display: "grid", gap: 12, marginTop: 12 }}>
          {step.children.map((child) => (
            <ReverseStepNode key={child.id} step={child} depth={depth + 1} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Line({ label, text, danger }: { label: string; text: string; danger?: boolean }) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
      <span style={{ minWidth: 56, color: danger ? colors.status.warning.text : colors.muted }}>
        {label}
      </span>
      <span style={{ color: colors.ink }}>{text}</span>
    </div>
  );
}
