"use client";

import { Alert, Button, Space } from "antd";
import type { ReactNode } from "react";
import { colors } from "@/lib/tokens";

export interface OperationBlockedItem {
  key: string;
  label?: string;
  title: string;
  detail?: ReactNode;
  status?: ReactNode;
  actionLabel?: string;
  onAction?: () => void;
  disabledReason?: string;
}

interface Props {
  title: string;
  nextAction?: string;
  fallbackText?: string;
  framed?: boolean;
  items?: OperationBlockedItem[];
}

export function OperationBlockedNotice({
  title,
  nextAction,
  fallbackText = "请先处理阻塞项,再重试当前操作。",
  framed = true,
  items = [],
}: Props) {
  const description = (
    <Space orientation="vertical" size={8} style={{ width: "100%" }}>
      <span style={{ color: colors.status.danger.text, fontWeight: 500 }}>
        {nextAction ?? fallbackText}
      </span>
      {items.length > 0 ? (
        <div style={{ display: "grid", gap: 8 }}>
          {items.map((item) => (
            <OperationBlockedRow key={item.key} item={item} />
          ))}
        </div>
      ) : null}
    </Space>
  );

  if (!framed) return description;

  return (
    <Alert
      type="error"
      showIcon
      title={<span style={{ color: colors.status.danger.text }}>{title}</span>}
      description={description}
    />
  );
}

function OperationBlockedRow({ item }: { item: OperationBlockedItem }) {
  const canOpen = Boolean(item.onAction);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
      }}
    >
      <Space size={8} wrap>
        {item.label ? <span>{item.label}</span> : null}
        {canOpen ? (
          <Button type="link" style={{ padding: 0 }} onClick={item.onAction}>
            {item.title}
          </Button>
        ) : (
          <span style={{ fontWeight: 600 }}>{item.title}</span>
        )}
        {item.status}
        {item.detail ? <span style={{ color: colors.ink }}>{item.detail}</span> : null}
        {!canOpen && item.disabledReason ? (
          <span style={{ color: colors.muted }}>{item.disabledReason}</span>
        ) : null}
      </Space>
      {canOpen && item.actionLabel ? (
        <Button size="small" onClick={item.onAction}>
          {item.actionLabel}
        </Button>
      ) : null}
    </div>
  );
}
