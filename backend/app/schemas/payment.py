"""付款单 schemas(付侧实层)。🔴红线域。status 值域 = model 层 PaymentStatus;
派生口径 = payment.derive_payment_status。supplier_id 必填(D1 无待认领态)。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class PaymentCreateIn(BaseModel):
    """登记付款。amount/currency/paid_at/supplier_id 必填(付款主动付给已知供应商,无待认领)。"""
    # Decimal 强校验(镜像 ReceiptCreateIn):> 0、两位小数、位数对齐 Numeric(18,2),脏输入 422 拒。
    amount: Decimal = Field(..., gt=0, max_digits=18, decimal_places=2,
                            description="付款金额,登记即定死,> 0,两位小数")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    paid_at: date
    supplier_id: int
    account_info: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class PaymentVoidIn(BaseModel):
    void_reason: str | None = Field(default=None, max_length=500)
