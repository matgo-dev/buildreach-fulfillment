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
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class CustomerRefundStatus:
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    VOIDED = "VOIDED"
    ALL = (PENDING_PAYMENT, PAID, VOIDED)


class CustomerRefund(Base, TimestampMixin):
    """客户退款单。

    公司承担型取消确认后生成,承载客户侧应退金额。付款执行可后续扩展,本单先作为
    待付款财务义务,不影响供应商应付。
    """
    __tablename__ = "customer_refunds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_PAYMENT','PAID','VOIDED')",
            name="ck_customer_refunds_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_customer_refunds_currency_iso4217"),
        CheckConstraint("amount > 0", name="ck_customer_refunds_amount_pos"),
        Index("uq_customer_refunds_preturn_active", "purchase_return_order_id", unique=True,
              postgresql_where=text("status <> 'VOIDED'")),
        Index("ix_customer_refunds_customer_created", "customer_id", text("created_at DESC")),
        Index("ix_customer_refunds_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    purchase_return_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_return_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=CustomerRefundStatus.PENDING_PAYMENT)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    paid_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
