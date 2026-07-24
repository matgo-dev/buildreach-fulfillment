"use client";

import { useState } from "react";
import { Checkbox, Segmented, Space, Typography } from "antd";
import { RouteGuard } from "@/components/auth/RouteGuard";
import { GuideChart } from "@/components/guide/GuideChart";
import { GUIDE_ROLE_OPTIONS } from "@/config/guideFlow";
import type { GuideNode, GuideRole } from "@/config/guideFlow";

export default function GuidePage() {
  const [activeNode, setActiveNode] = useState<GuideNode | null>(null);
  const [highlightRole, setHighlightRole] = useState<GuideRole | null>(null);
  const [showMoney, setShowMoney] = useState(false);
  const [showMaster, setShowMaster] = useState(false);

  return (
    <RouteGuard>
      <div style={{ padding: 24, maxWidth: 1280 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>
          平台导览
        </Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 20 }}>
          一单货从接到客户询价,到最后收清货款,在这个平台里要经过下面这些步骤。点任意一步看详细说明。
        </Typography.Paragraph>

        <div style={{ marginBottom: 16 }}>
          <Space size={20} style={{ marginBottom: 12 }}>
            <Checkbox checked={showMoney} onChange={(e) => setShowMoney(e.target.checked)}>
              看钱怎么走
            </Checkbox>
            <Checkbox checked={showMaster} onChange={(e) => setShowMaster(e.target.checked)}>
              看基础资料从哪来
            </Checkbox>
          </Space>
          <div style={{ display: "flex", alignItems: "flex-start", gap: 16 }}>
            <div style={{ flex: 1 }}>
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
        </div>

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
