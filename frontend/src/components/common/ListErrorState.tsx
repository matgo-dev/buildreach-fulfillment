"use client";
import { Button } from "antd";
import { colors } from "@/lib/tokens";

/** 列表加载失败态:居中「加载失败」+ 重试按钮(样式取自各列表页既有实现,逐字一致)。 */
export function ListErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div style={{ textAlign: "center", padding: "48px 0", color: colors.muted }}>
      加载失败
      <div style={{ marginTop: 12 }}>
        <Button onClick={onRetry}>重试</Button>
      </div>
    </div>
  );
}
