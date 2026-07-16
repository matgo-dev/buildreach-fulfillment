import { Tag, Tooltip } from "antd";
import { colors } from "@/lib/tokens";

/**
 * 次要在途信号:采购单已有 N 张「在途」入库单(已登记、未确认收货)。
 *
 * 与收货进度徽标(实收口径的语义状态色)刻意区分——弱化为无边框 muted chip,
 * 读作「有货在路上」的注解,而非收货态。收货进度 3 态口径保持干净不受污染。
 * 列表 / 详情 / 选单器三处共用此单一源头。count ≤ 0 不渲染。
 */
export function InTransitBadge({ count }: { count?: number | null }) {
  if (!count || count <= 0) return null;
  return (
    <Tooltip title="已登记、尚未确认收货的入库单数量">
      <Tag bordered={false} style={{ color: colors.muted, marginInlineEnd: 0 }}>
        在途 {count}
      </Tag>
    </Tooltip>
  );
}
