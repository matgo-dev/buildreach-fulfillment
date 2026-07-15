"""销售单 schemas。转销售(锁档报价→销售单)本增量:只读投影,无写 schema(create 走 convert)。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SalesOrderOut(BaseModel):
    id: int
    no: str
    source_quotation_id: int
    customer_id: int
    salesperson_id: int
    language: str
    currency: str
    status: str
    total_amount: float
    summary: str | None
    remark: str | None
    updated_at: datetime


class SalesOrderLineOut(BaseModel):
    id: int
    sales_order_id: int
    sku_id: int
    source_quotation_line_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    unit_price: float
    qty: float
    line_total: float
    remark: str | None
    language: str
    sort_order: int


class SalesOrderListItem(BaseModel):
    id: int
    no: str
    summary: str | None
    customer_display: str
    salesperson_display: str
    status: str
    currency: str
    total_amount: float
    line_count: int
    created_at: datetime
