from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import LineQty


class CustomerReturnLineIn(BaseModel):
    outbound_order_line_id: int
    qty: LineQty
    remark: str | None = None
    sort_order: int = Field(default=0, ge=0)


class CustomerReturnCreateIn(BaseModel):
    outbound_order_id: int
    reason: str | None = None
    lines: list[CustomerReturnLineIn] = Field(default_factory=list)


class CustomerReturnLineOut(BaseModel):
    id: int
    customer_return_order_id: int
    outbound_order_line_id: int
    sales_order_line_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    language: str
    qty: float
    sort_order: int
    remark: str | None

    @classmethod
    def build(cls, line) -> dict:
        return {
            "id": line.id,
            "customer_return_order_id": line.customer_return_order_id,
            "outbound_order_line_id": line.outbound_order_line_id,
            "sales_order_line_id": line.sales_order_line_id,
            "sku_id": line.sku_id,
            "name_snapshot": line.name_snapshot,
            "spec_text_snapshot": line.spec_text_snapshot,
            "unit_snapshot": line.unit_snapshot,
            "language": line.language,
            "qty": float(line.qty),
            "sort_order": line.sort_order,
            "remark": line.remark,
        }


class CustomerReturnOut(BaseModel):
    id: int
    no: str
    outbound_order_id: int
    sales_order_id: int
    customer_id: int
    status: str
    reason: str | None
    received_at: datetime
    received_by: int
    created_by: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, order) -> dict:
        return cls.model_validate(order, from_attributes=True).model_dump()


class CustomerReturnTraceOut(BaseModel):
    purchase_order_ids: list[int]
    inbound_order_ids: list[int]


class CustomerReturnDetailOut(BaseModel):
    order: CustomerReturnOut
    lines: list[CustomerReturnLineOut]
    trace: CustomerReturnTraceOut
