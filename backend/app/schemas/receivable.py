"""应收款 schemas。

🔴 整表红线域(客户售价):仅在持 receivable:read 的端点出现,不做字段级脱敏(整端点即红线门)。
status(未收/部分收/已收清)由 amount_* 派生输出(derive_receivable_status,单一口径)。
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from app.db.models.receivable import derive_receivable_status


class ReceivableListItem(BaseModel):
    id: int
    outbound_order_id: int
    outbound_order_no: str
    sales_order_id: int
    sales_order_no: str
    customer_id: int
    customer_display: str
    currency: str
    amount_original: float
    amount_allocated: float
    balance: float
    status: str
    due_at: date | None
    created_at: datetime

    @classmethod
    def build(cls, item: dict) -> dict:
        return {
            **{k: item[k] for k in (
                "id", "outbound_order_id", "outbound_order_no", "sales_order_id",
                "sales_order_no", "customer_id", "customer_display", "currency", "due_at",
                "created_at")},
            "amount_original": float(item["amount_original"]),
            "amount_allocated": float(item["amount_allocated"]),
            "balance": float(item["balance"]),
            "status": derive_receivable_status(item["amount_original"], item["amount_allocated"]),
        }
