// 库存(订单履约跟踪)前端类型 + API。对齐后端 stock_balance_service.compute_stock_balance。
// 🔴 纯派生,零成本/供应商字段 —— 读投影天然无红线,零脱敏分支(契约 §3)。
import { api } from "./api";
import type { Page } from "./catalog";

/** `/api/v1/inventory` 列表行(契约 §3 逐字字段)。 */
export interface StockBalanceItem {
  sales_order_id: number;
  sales_order_no: string;
  sku_code: string;
  name: string;
  spec_text: string;
  unit: string;
  ordered_qty: number | string;
  inbound_qty: number | string;
  outbound_qty: number | string;
  available_qty: number | string;
}

/** SO 详情内嵌块(契约 §3:该 SO 各 SKU 四量,含已入 0 行)。附 sku_id 供行 key/未来下钻。 */
export interface StockBalanceLine {
  sku_id: number;
  sku_code: string;
  name: string;
  spec_text: string;
  unit: string;
  ordered_qty: number | string;
  inbound_qty: number | string;
  outbound_qty: number | string;
  available_qty: number | string;
}

export interface InventoryListFilters {
  sales_order_id?: number;
  sku_id?: number;
  q?: string;
  /** 默认口径省略 = available_qty>0(在库);传 "history" = 含已履约行(契约 §2/§5)。 */
  scope?: "history";
  page?: number;
  size?: number;
}

function qs(p: Record<string, unknown>): string {
  const q = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  });
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const inventoryApi = {
  list: (p: InventoryListFilters) =>
    api.get<Page<StockBalanceItem>>(`/api/v1/inventory${qs(p as Record<string, unknown>)}`),
};
