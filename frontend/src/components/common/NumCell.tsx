// 数字单元:tabular-nums 对齐(DESIGN §2 数字列)。数量列渲染的单一源头,
// 消费方:库存列表 / SO 详情库存块 / 入库建单器。
// muted = 参考性次要数字弱化;strong = 约束基准/关键量强调;空值 → 弱化占位 "—"。
import { colors } from "@/lib/tokens";
import { formatQty } from "@/lib/format";

export function NumCell({ value, muted, strong }: {
  value?: number | string | null;
  muted?: boolean;
  strong?: boolean;
}) {
  if (value === undefined || value === null) {
    return <span style={{ color: colors.muted }}>—</span>;
  }
  return (
    <span
      style={{
        fontVariantNumeric: "tabular-nums",
        color: muted ? colors.muted : undefined,
        fontWeight: strong ? 600 : undefined,
      }}
    >
      {formatQty(value)}
    </span>
  );
}
