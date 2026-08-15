"""应付款 schemas。

🔴 整表红线域:仅在持 payable:read 的端点/块出现,不做字段级脱敏(整端点/整块即红线门)。
status(未付/部分付/已付清)由 amount_* 派生输出(derive_payable_status,单一口径)。
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from app.db.models.payable import derive_payable_status


class PayableOut(BaseModel):
    """入库详情 payable 块(有活动应付且持 payable:read 时下发)。"""
    id: int
    inbound_order_id: int
    purchase_order_id: int
    supplier_id: int
    currency: str
    amount_original: float
    amount_allocated: float
    balance: float
    status: str
    due_at: date | None
    created_at: datetime

    @classmethod
    def build(cls, p) -> dict:
        return {
            "id": p.id, "inbound_order_id": p.inbound_order_id,
            "purchase_order_id": p.purchase_order_id, "supplier_id": p.supplier_id,
            "currency": p.currency, "amount_original": float(p.amount_original),
            "amount_allocated": float(p.amount_allocated), "balance": float(p.balance),
            "status": derive_payable_status(p.amount_original, p.amount_allocated),
            "due_at": p.due_at, "created_at": p.created_at,
        }


class PayableListItem(BaseModel):
    id: int
    inbound_order_id: int
    inbound_order_no: str
    purchase_order_id: int
    purchase_order_no: str
    supplier_id: int
    supplier_display: str
    currency: str
    amount_original: float
    amount_allocated: float
    balance: float
    status: str
    due_at: date | None
    created_at: datetime
    # D10:该供应商是否有未分配付款余额(预付),供列表提示「一键核销」入口(纯提示,非自动)。
    counterparty_has_unallocated: bool = False

    @classmethod
    def build(cls, item: dict) -> dict:
        return {
            **{k: item[k] for k in (
                "id", "inbound_order_id", "inbound_order_no", "purchase_order_id",
                "purchase_order_no", "supplier_id", "supplier_display", "currency", "due_at",
                "created_at")},
            "amount_original": float(item["amount_original"]),
            "amount_allocated": float(item["amount_allocated"]),
            "balance": float(item["balance"]),
            "status": derive_payable_status(item["amount_original"], item["amount_allocated"]),
            "counterparty_has_unallocated": item.get("counterparty_has_unallocated", False),
        }
