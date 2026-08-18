"""库存(订单履约跟踪)读投影。纯派生四量 + 展示三件套(SKU 当前档)。
无成本/供应商/金额字段 → 零红线、零脱敏分支。"""
from __future__ import annotations

from pydantic import BaseModel


class StockBalanceRow(BaseModel):
    """每 (销售单, SKU) 一行:订购/已入库/已出库(本步恒 0)/可发。
    展示字段(品名/规格串/单位)取 SKU 当前档,按所属 SO 语言渲染。"""
    sales_order_id: int
    sales_order_no: str
    sku_id: int
    sku_code: str
    name: str
    spec_text: str
    unit: str
    ordered_qty: float
    inbound_qty: float
    outbound_qty: float
    disposition_qty: float
    available_qty: float
