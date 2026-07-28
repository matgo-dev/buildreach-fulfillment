// 展示格式化的单一源头:金额 / 数量 / 时间。各域格式化(formatCost/formatAmount)从此派生。

/** 金额格式化:固定 2 位小数(单价/金额/总额)。 */
export function formatMoney(v: number | string): string {
  return Number(v).toLocaleString(undefined, { minimumFractionDigits: 2 });
}

/** 数量格式化:最多 3 位小数、不补零(qty 为 Numeric(18,3),整数不应显示成 x.00)。 */
export function formatQty(v: number | string): string {
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 3 });
}

const DATE_TIME_PARTS = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function utcDateTime(v: string): Date {
  // 后端 created_at/updated_at 是 naive UTC。无时区后缀时按 UTC 解释,再交给浏览器本地时区展示。
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(v);
  return new Date(hasZone ? v : `${v}Z`);
}

/** ISO 时间串 → 浏览器本地时区 "YYYY-MM-DD HH:mm"。空值原样透传(列表渲染空单元格)。 */
export function formatDateTime(v: string | null | undefined): string | null | undefined {
  if (!v) return v;
  const parts = DATE_TIME_PARTS.formatToParts(utcDateTime(v));
  const byType = Object.fromEntries(parts.map((p) => [p.type, p.value]));
  return `${byType.year}-${byType.month}-${byType.day} ${byType.hour}:${byType.minute}`;
}
