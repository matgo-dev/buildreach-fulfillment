"""收款单 schemas(收侧实层)。status 值域单一源头 = model 层 ReceiptStatus;
派生口径唯一源头 = receipt.derive_receipt_status。

内嵌核销记录的应收额按 D9 门控:无 receivable:read 者,allocation.account_amount 脱敏为 null
(权限跟数据走,不跟页面走——避免只持 receipt:read 者经收款详情旁路读到 AR 额)。
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ReceiptCreateIn(BaseModel):
    """登记收款。amount/currency/received_at 必填;customer_id 可空 = 待认领。"""
    amount: str = Field(..., description="到账金额,登记即定死,> 0")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    received_at: date
    customer_id: int | None = None
    account_info: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class ReceiptClaimIn(BaseModel):
    """认领客户(仅 UNCLAIMED 收款单可认领)。"""
    customer_id: int


class ReceiptVoidIn(BaseModel):
    void_reason: str | None = Field(default=None, max_length=500)


class ManualAllocateIn(BaseModel):
    """人工改分配:指定应收/应付,金额自动取满 min(未分配, 余额),不由用户自填(D8)。"""
    account_id: int = Field(..., description="receivable_id(收侧)/ payable_id(付侧)")

# 反核销 reverse_reason 走 query 参数(DELETE body 公网代理不可靠),无请求体 schema。
