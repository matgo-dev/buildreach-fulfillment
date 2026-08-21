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
    reject_reason: str = Field(..., min_length=1, max_length=500)


class CustomerCreditMemoResubmitIn(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2)
    reason: str | None = Field(default=None, max_length=500)


class CustomerCreditMemoAllocateIn(BaseModel):
    account_id: int = Field(..., description="receivable_id")
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    idempotency_key: str = Field(..., min_length=1, max_length=120)


class CustomerCreditMemoVoidIn(BaseModel):
    void_reason: str | None = Field(default=None, max_length=500)


class CustomerCreditAllocationReverseIn(BaseModel):
    reverse_reason: str | None = Field(default=None, max_length=500)


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
    resubmitted_from_id: int | None
    voided_at: datetime | None
    voided_by: int | None
    void_reason: str | None
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
            "resubmitted_from_id": memo.resubmitted_from_id,
            "voided_at": memo.voided_at,
            "voided_by": memo.voided_by,
            "void_reason": memo.void_reason,
            "created_by": memo.created_by,
            "created_at": memo.created_at,
        }


class CustomerCreditAllocationOut(BaseModel):
    id: int
    customer_credit_memo_id: int
    receivable_id: int
    account_id: int
    account_no: str
    outbound_order_id: int
    amount: Decimal
    alloc_type: str
    source_type: str = "CUSTOMER_CREDIT_MEMO"
    idempotency_key: str
    created_by: int
    created_at: datetime

    @classmethod
    def build(cls, row) -> dict:
        alloc, outbound_order_id, outbound_no = row
        return {
            "id": alloc.id,
            "customer_credit_memo_id": alloc.customer_credit_memo_id,
            "receivable_id": alloc.receivable_id,
            "account_id": alloc.receivable_id,
            "account_no": outbound_no,
            "outbound_order_id": outbound_order_id,
            "amount": Decimal(str(alloc.amount)),
            "alloc_type": alloc.alloc_type,
            "source_type": "CUSTOMER_CREDIT_MEMO",
            "idempotency_key": alloc.idempotency_key,
            "created_by": alloc.created_by,
            "created_at": alloc.created_at,
        }


class CustomerCreditMemoDetailOut(BaseModel):
    memo: CustomerCreditMemoOut
    allocations: list[CustomerCreditAllocationOut]

    @classmethod
    def build(cls, detail: dict) -> dict:
        return {
            "memo": CustomerCreditMemoOut.build(detail["memo"]),
            "allocations": [
                CustomerCreditAllocationOut.build(row)
                for row in detail["allocations"]
            ],
        }
