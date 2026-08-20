from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CustomerCreditMemoCreateIn(BaseModel):
    inventory_disposition_order_id: int
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    currency: Literal["CNY"] = "CNY"
    reason: str | None = Field(default=None, max_length=500)


class CustomerCreditMemoRejectIn(BaseModel):
    reject_reason: str | None = Field(default=None, max_length=500)


class CustomerCreditMemoOut(BaseModel):
    id: int
    no: str
    inventory_disposition_order_id: int
    sales_order_id: int
    customer_id: int
    currency: str
    memo_type: str
    status: str
    amount: Decimal
    amount_allocated: Decimal
    amount_unallocated: Decimal
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
        return {
            "id": memo.id,
            "no": memo.no,
            "inventory_disposition_order_id": memo.inventory_disposition_order_id,
            "sales_order_id": memo.sales_order_id,
            "customer_id": memo.customer_id,
            "currency": memo.currency,
            "memo_type": memo.memo_type,
            "status": memo.status,
            "amount": Decimal(str(memo.amount)),
            "amount_allocated": Decimal(str(memo.amount_allocated)),
            "amount_unallocated": Decimal(str(memo.amount_unallocated)),
            "reason": memo.reason,
            "posted_at": memo.posted_at,
            "posted_by": memo.posted_by,
            "rejected_at": memo.rejected_at,
            "rejected_by": memo.rejected_by,
            "reject_reason": memo.reject_reason,
            "created_by": memo.created_by,
            "created_at": memo.created_at,
        }
