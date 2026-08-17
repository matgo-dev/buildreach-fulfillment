from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ReverseRequestCreateIn(BaseModel):
    inbound_order_id: int
    reason: str = Field(min_length=1, max_length=2000)


class ReverseRequestApproveIn(BaseModel):
    supplier_resolution: Literal["SUPPLIER_ACCEPTS_RETURN", "COMPANY_BEAR_LOSS"]
    review_note: str | None = Field(default=None, max_length=2000)


class ReverseRequestRejectIn(BaseModel):
    review_note: str | None = Field(default=None, max_length=2000)


class ReverseRequestCompleteIn(BaseModel):
    completion_note: str | None = Field(default=None, max_length=2000)


class ReverseRequestOut(BaseModel):
    id: int
    no: str
    request_type: str
    status: str
    sales_order_id: int
    purchase_order_id: int
    inbound_order_id: int
    goods_status: str
    supplier_resolution: str | None
    reason: str
    review_note: str | None
    completion_note: str | None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None
    completed_at: datetime | None
    sales_order_no: str | None = None
    purchase_order_no: str | None = None
    inbound_order_no: str | None = None
    customer_display: str | None = None
    supplier_display: str | None = None

    @classmethod
    def build(cls, request, extra: dict | None = None) -> dict:
        d = cls.model_validate(request, from_attributes=True).model_dump()
        if extra:
            d.update(extra)
        return d


class ReverseRequestLineOut(BaseModel):
    id: int
    reverse_request_id: int
    inbound_order_line_id: int
    purchase_order_line_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    qty: float

    @classmethod
    def build(cls, line) -> dict:
        return cls.model_validate(line, from_attributes=True).model_dump()


class ReverseRequestListItem(BaseModel):
    id: int
    no: str
    request_type: str
    status: str
    sales_order_id: int
    purchase_order_id: int
    inbound_order_id: int
    sales_order_no: str
    purchase_order_no: str
    inbound_order_no: str
    customer_display: str
    supplier_display: str
    goods_status: str
    supplier_resolution: str | None
    line_count: int
    total_qty: float
    created_at: datetime
