from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PaymentAllocation(Base):
    """付款核销记录(核销层,付侧)。完全对称 ReceiptAllocation:把一笔付款勾到一张应付款。🔴红线域。

    反核销 = 软删留痕(reversed_at)。活动核销 = reversed_at IS NULL。核销引擎是
    payments/payables 的 amount_allocated 唯一写入口。alloc_type 复用 AllocationType(AUTO/MANUAL)。
    """
    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_alloc_amount_pos"),
        CheckConstraint("alloc_type IN ('AUTO','MANUAL')", name="ck_payment_alloc_type"),
        Index("uq_payment_alloc_active", "payment_id", "payable_id", unique=True,
              postgresql_where=text("reversed_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, index=True)
    payable_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payables.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    alloc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reversed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    reverse_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()"))
