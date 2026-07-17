// 展示格式化的单一源头:金额 / 数量 / 时间。各域格式化(formatCost/formatAmount)从此派生。

/** 金额格式化:固定 2 位小数(单价/金额/总额)。 */
export function formatMoney(v: number | string): string {
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 });
}

/** 数量格式化:最多 3 位小数、不补零(qty 为 Numeric(18,3),整数不应显示成 x.00)。 */
export function formatQty(v: number | string): string {
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
}

/** ISO 时间串 → "YYYY-MM-DD HH:mm"(截到分)。空值原样透传(列表渲染空单元格)。 */
export function formatDateTime(v: string | null | undefined): string | null | undefined {
  return v?.replace("T", " ").slice(0, 16);
}
