"use client";

import { Button, Card, Space, Typography } from "antd";
import { PlayCircleOutlined } from "@ant-design/icons";
import { TOUR_SEQUENCE, guideNodeById } from "@/config/guideFlow";

interface Props {
  /** null = 未开始 */
  stepIndex: number | null;
  onStart: () => void;
  onPrev: () => void;
  onNext: () => void;
  onExit: () => void;
}

export function GuideTour({ stepIndex, onStart, onPrev, onNext, onExit }: Props) {
  if (stepIndex === null) {
    return (
      <Button icon={<PlayCircleOutlined />} onClick={onStart}>
        跟一单货走一遍
      </Button>
    );
  }

  const node = guideNodeById(TOUR_SEQUENCE[stepIndex]);
  const total = TOUR_SEQUENCE.length;

  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          第 {stepIndex + 1} / {total} 步 · {node?.action}
        </Typography.Text>
        <Typography.Paragraph style={{ marginBottom: 0, fontSize: 14 }}>
          {node?.narration}
        </Typography.Paragraph>
        <Space>
          <Button size="small" disabled={stepIndex === 0} onClick={onPrev}>
            上一步
          </Button>
          <Button
            size="small"
            type="primary"
            disabled={stepIndex === total - 1}
            onClick={onNext}
          >
            下一步
          </Button>
          <Button size="small" type="text" onClick={onExit}>
            退出
          </Button>
        </Space>
      </Space>
    </Card>
  );
}
