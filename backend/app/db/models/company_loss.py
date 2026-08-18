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


class CompanyLossEntryStatus:
    POSTED = "POSTED"
    VOIDED = "VOIDED"
    ALL = (POSTED, VOIDED)


class CompanyLossEntry(Base, TimestampMixin):
    """公司损失确认单。

    金额口径为保留供应商应付成本 + 客户退款金额。它是公司承担型取消的财务侧闭环,
    与供应商贷项单互斥,不改写 payable.amount_credited。
    """
    __tablename__ = "company_loss_entries"
    __table_args__ = (
        CheckConstraint("status IN ('POSTED','VOIDED')", name="ck_company_losses_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_company_losses_currency_iso4217"),
        CheckConstraint("amount > 0", name="ck_company_losses_amount_pos"),
        CheckConstraint("supplier_payable_amount >= 0",
                        name="ck_company_losses_supplier_payable_nn"),
        CheckConstraint("customer_refund_amount >= 0",
                        name="ck_company_losses_customer_refund_nn"),
        CheckConstraint("amount = supplier_payable_amount + customer_refund_amount",
                        name="ck_company_losses_amount_identity"),
        Index("uq_company_losses_preturn_active", "purchase_return_order_id", unique=True,
              postgresql_where=text("status <> 'VOIDED'")),
        Index("ix_company_losses_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    purchase_return_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_return_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    payable_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payables.id", ondelete="RESTRICT"), nullable=False, index=True)
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=CompanyLossEntryStatus.POSTED)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    supplier_payable_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    customer_refund_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    posted_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
