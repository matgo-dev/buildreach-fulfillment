"use client";

import { Drawer, Typography } from "antd";
import type { GuideNode } from "@/config/guideFlow";
import { ROLE_META } from "@/lib/user";
import { GUIDE_ICONS } from "./guideIcons";

const { Paragraph, Text } = Typography;

export function GuideDrawer({ node, onClose }: { node: GuideNode | null; onClose: () => void }) {
  return (
    <Drawer
      open={node !== null}
      onClose={onClose}
      width={440}
      title={
        node && (
          <span>
            <span style={{ marginRight: 8 }}>{GUIDE_ICONS[node.iconKey]}</span>
            {node.action}
            <Text type="secondary" style={{ fontSize: 12, marginLeft: 8, fontWeight: 400 }}>
              {node.docName}
            </Text>
          </span>
        )
      }
    >
      {node && (
        <>
          <Section title="这一步在做什么">{node.what}</Section>
          <Section title="谁来做">{ROLE_META[node.role]}</Section>
          <Section title="上一步是什么、下一步去哪">{node.fromTo}</Section>
          <Section title="做完之后系统里发生了什么">{node.effect}</Section>
        </>
      )}
    </Drawer>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 24 }}>
      <Text strong style={{ display: "block", marginBottom: 8 }}>
        {title}
      </Text>
      <Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{children}</Paragraph>
    </div>
  );
}
