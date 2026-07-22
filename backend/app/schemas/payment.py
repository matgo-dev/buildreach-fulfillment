"""付款单 schemas(付侧实层)。🔴红线域。status 值域 = model 层 PaymentStatus;
派生口径 = payment.derive_payment_status。supplier_id 必填(D1 无待认领态)。
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class PaymentCreateIn(BaseModel):
    """登记付款。amount/currency/paid_at/supplier_id 必填(付款主动付给已知供应商,无待认领)。"""
    amount: str = Field(..., description="付款金额,登记即定死,> 0")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    paid_at: date
    supplier_id: int
    account_info: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class PaymentVoidIn(BaseModel):
    void_reason: str | None = Field(default=None, max_length=500)
