"""报价单 schemas。"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class QuotationCreateIn(BaseModel):
    customer_id: int
    currency: str = Field(..., max_length=10)
    valid_until: date | None = None
    remark: str | None = None


class QuotationLineIn(BaseModel):
    sku_id: int
    unit_price: float
    qty: float
    # 快照可编辑覆盖(线下定稿措辞优先);不传则由 SKU + 模板按报价语言组合默认
    name_snapshot: str | None = None
    spec_text_snapshot: str | None = None
    unit_snapshot: str | None = None
    sort_order: int = 0


class QuotationOrderOut(BaseModel):
    id: int
    no: str
    customer_id: int
    language: str
    currency: str
    valid_until: date | None
    status: str
    remark: str | None


class QuotationLineOut(BaseModel):
    id: int
    quotation_order_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    unit_price: float
    qty: float
    line_total: float
    language: str
    sort_order: int
