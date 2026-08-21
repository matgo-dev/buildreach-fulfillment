from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.customer_credit_memo import CustomerCreditMemoOut


class InventoryDispositionCreateIn(BaseModel):
    inbound_order_id: int
    receipt_handling: str
    reason: str | None = None


class InventoryDispositionLineOut(BaseModel):
    id: int
    inventory_disposition_order_id: int
    inbound_order_line_id: int
    purchase_order_line_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    language: str
    qty: float
    unit_cost: float | None = None
    line_cost: float | None = None
    sort_order: int
    remark: str | None

    @classmethod
    def build(cls, line, *, can_see_cost: bool) -> dict:
        return {
            "id": line.id,
            "inventory_disposition_order_id": line.inventory_disposition_order_id,
            "inbound_order_line_id": line.inbound_order_line_id,
            "purchase_order_line_id": line.purchase_order_line_id,
            "sku_id": line.sku_id,
            "name_snapshot": line.name_snapshot,
            "spec_text_snapshot": line.spec_text_snapshot,
            "unit_snapshot": line.unit_snapshot,
            "language": line.language,
            "qty": float(line.qty),
            "unit_cost": float(line.unit_cost) if can_see_cost else None,
            "line_cost": float(line.line_cost) if can_see_cost else None,
            "sort_order": line.sort_order,
            "remark": line.remark,
        }


class InventoryDispositionOut(BaseModel):
    id: int
    no: str
    inbound_order_id: int
    purchase_order_id: int
    sales_order_id: int
    payable_id: int
    purchase_currency: str
    status: str
    receipt_handling: str
    supplier_payable_amount: float | None = None
    reason: str | None
    held_at: datetime | None
    held_by: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(cls, order, *, can_see_cost: bool) -> dict | None:
        if order is None:
            return None
        return {
            "id": order.id,
            "no": order.no,
            "inbound_order_id": order.inbound_order_id,
            "purchase_order_id": order.purchase_order_id,
            "sales_order_id": order.sales_order_id,
            "payable_id": order.payable_id,
            "purchase_currency": order.purchase_currency,
            "status": order.status,
            "receipt_handling": order.receipt_handling,
            "supplier_payable_amount": (
                float(order.supplier_payable_amount) if can_see_cost else None
            ),
            "reason": order.reason,
            "held_at": order.held_at,
            "held_by": order.held_by,
            "created_at": order.created_at,
            "updated_at": order.updated_at,
        }


class InventoryDispositionDetail(BaseModel):
    order: InventoryDispositionOut
    lines: list[InventoryDispositionLineOut]
    customer_credit_memo: CustomerCreditMemoOut | None = None
