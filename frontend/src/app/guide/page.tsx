"use client";

import { useState } from "react";
import { Typography } from "antd";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { GuideChart } from "@/components/guide/GuideChart";
import type { GuideNode, GuideRole } from "@/config/guideFlow";

export default function GuidePage() {
  const [activeNode, setActiveNode] = useState<GuideNode | null>(null);
  const [highlightRole] = useState<GuideRole | null>(null);
  const [showMoney] = useState(false);
  const [showMaster] = useState(false);

  return (
    <RouteGuard>
      <div style={{ padding: 24, maxWidth: 1280 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          平台导览
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>
          一单货从接到客户询价,到最后收清货款,在这个平台里要经过下面这些步骤。点任意一步看详细说明。
        </Typography.Paragraph>

        <GuideChart
          showMoney={showMoney}
          showMaster={showMaster}
          highlightRole={highlightRole}
          activeId={activeNode?.id ?? null}
          onNodeClick={setActiveNode}
        />
      </div>
    </RouteGuard>
  );
}
