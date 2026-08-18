from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import LineQty


class PurchaseReturnLineIn(BaseModel):
    inbound_order_line_id: int
    qty: LineQty
    remark: str | None = None
    sort_order: int = Field(default=0, ge=0)


class PurchaseReturnCreateIn(BaseModel):
    inbound_order_id: int
    reason: str | None = None
    lines: list[PurchaseReturnLineIn] = Field(default_factory=list)


class RejectIn(BaseModel):
    reject_reason: str | None = None


class ConfirmReturnShipmentIn(BaseModel):
    return_shipment_reference: str | None = Field(default=None, max_length=80)
    return_note: str | None = None


class InTransitCancellationCreateIn(BaseModel):
    inbound_order_id: int
    reason: str | None = None


class ConfirmInTransitCancellationIn(BaseModel):
    cancellation_reference: str | None = Field(default=None, max_length=80)
    cancellation_note: str | None = None


class PurchaseReturnableLineOut(BaseModel):
    inbound_order_line_id: int
    purchase_order_line_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    language: str
    received_qty: float
    returned_qty: float
    in_process_return_qty: float
    returnable_qty: float
    remark: str | None


class PurchaseReturnLineOut(BaseModel):
    id: int
    purchase_return_order_id: int
    inbound_order_line_id: int
    purchase_order_line_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    language: str
    qty: float
    unit_price: float | None = None
    line_total: float | None = None
    sort_order: int
    remark: str | None

    @classmethod
    def build(cls, line, *, can_see_cost: bool) -> dict:
        return {
            "id": line.id,
            "purchase_return_order_id": line.purchase_return_order_id,
            "inbound_order_line_id": line.inbound_order_line_id,
            "purchase_order_line_id": line.purchase_order_line_id,
            "sku_id": line.sku_id,
            "name_snapshot": line.name_snapshot,
            "spec_text_snapshot": line.spec_text_snapshot,
            "unit_snapshot": line.unit_snapshot,
            "language": line.language,
            "qty": float(line.qty),
            "unit_price": float(line.unit_price) if can_see_cost else None,
            "line_total": float(line.line_total) if can_see_cost else None,
            "sort_order": line.sort_order,
            "remark": line.remark,
        }


class APCreditMemoOut(BaseModel):
    id: int
    no: str
    payable_id: int
    purchase_return_order_id: int
    supplier_id: int
    currency: str
    memo_type: str
    status: str
    amount: float
    reason: str | None
    posted_at: datetime | None
    posted_by: int | None
    rejected_at: datetime | None
    rejected_by: int | None
    reject_reason: str | None
    created_by: int
    created_at: datetime

    @classmethod
    def build(cls, memo) -> dict | None:
        if memo is None:
            return None
        return cls.model_validate(memo, from_attributes=True).model_dump()


class PurchaseReturnOut(BaseModel):
    id: int
    no: str
    inbound_order_id: int
    purchase_order_id: int
    sales_order_id: int
    supplier_id: int
    currency: str
    status: str
    return_kind: str
    total_amount: float | None = None
    reason: str | None
    submitted_at: datetime
    approved_at: datetime | None
    approved_by: int | None
    rejected_at: datetime | None
    rejected_by: int | None
    reject_reason: str | None
    returned_at: datetime | None
    returned_by: int | None
    return_shipment_reference: str | None
    return_note: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, order, *, can_see_cost: bool) -> dict:
        return {
            "id": order.id,
            "no": order.no,
            "inbound_order_id": order.inbound_order_id,
            "purchase_order_id": order.purchase_order_id,
            "sales_order_id": order.sales_order_id,
            "supplier_id": order.supplier_id,
            "currency": order.currency,
            "status": order.status,
            "return_kind": order.return_kind,
            "total_amount": float(order.total_amount) if can_see_cost else None,
            "reason": order.reason,
            "submitted_at": order.submitted_at,
            "approved_at": order.approved_at,
            "approved_by": order.approved_by,
            "rejected_at": order.rejected_at,
            "rejected_by": order.rejected_by,
            "reject_reason": order.reject_reason,
            "returned_at": order.returned_at,
            "returned_by": order.returned_by,
            "return_shipment_reference": order.return_shipment_reference,
            "return_note": order.return_note,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }


class PurchaseReturnListItem(BaseModel):
    id: int
    no: str
    status: str
    return_kind: str
    inbound_order_id: int
    inbound_order_no: str
    purchase_order_id: int
    purchase_order_no: str
    sales_order_id: int
    supplier_id: int
    currency: str
    total_amount: float | None = None
    line_count: int
    total_qty: float
    ap_credit_memo_status: str | None = None
    submitted_at: datetime
    created_at: datetime

    @classmethod
    def build(cls, item: dict, *, can_see_cost: bool) -> dict:
        out = dict(item)
        out["total_amount"] = float(item["total_amount"]) if can_see_cost else None
        return out
