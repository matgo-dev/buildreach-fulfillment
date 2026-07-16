// 业务币种可选值 —— 前端唯一源头(报价 / 供应商 / 采购 / 应付共用,别在页面各列一份)。
// ISO4217 三字母 code;后端 DB CHECK 只锁格式(^[A-Z]{3}$)不锁值域,业务扩币种改这里即可。
export const CURRENCIES = ["USD", "CNY", "KES", "TZS", "EUR"] as const;

/** AntD Select options 形态(各页共用,免每处重复 map)。 */
export const CURRENCY_OPTIONS = CURRENCIES.map((c) => ({ value: c, label: c }));
