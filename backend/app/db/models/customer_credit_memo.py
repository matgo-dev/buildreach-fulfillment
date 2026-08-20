from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
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


class CustomerCreditMemoStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    POSTED = "POSTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"
    ALL = (PENDING_APPROVAL, POSTED, REJECTED, VOIDED)


class CustomerCreditMemoType:
    INVENTORY_DISPOSITION = "INVENTORY_DISPOSITION"
    ALL = (INVENTORY_DISPOSITION,)


class CustomerCreditMemo(Base, TimestampMixin):
    """客户余额贷项单。

    1.3 供应商不接受、公司承担场景下,库存处置单只承载履约/库存事实;
    客户侧补偿金额以 CNY 客户贷方来源单据入账。过账后该单据的未分配余额
    即客户可用余额,后续提现/冲抵再由独立财务单据扣减。
    """
    __tablename__ = "customer_credit_memos"
    __table_args__ = (
        CheckConstraint(
            "memo_type IN ('INVENTORY_DISPOSITION')",
            name="ck_customer_credit_memos_type"),
        CheckConstraint(
            "status IN ('PENDING_APPROVAL','POSTED','REJECTED','VOIDED')",
            name="ck_customer_credit_memos_status"),
        CheckConstraint("currency = 'CNY'", name="ck_customer_credit_memos_currency_cny"),
        CheckConstraint("amount > 0", name="ck_customer_credit_memos_amount_pos"),
        CheckConstraint(
            "amount_allocated >= 0 AND amount_allocated <= amount",
            name="ck_customer_credit_memos_allocated_range"),
        CheckConstraint(
            "(status = 'POSTED') = (posted_at IS NOT NULL AND posted_by IS NOT NULL)",
            name="ck_customer_credit_memos_post_trace"),
        CheckConstraint(
            "(status = 'REJECTED') = (rejected_at IS NOT NULL AND rejected_by IS NOT NULL)",
            name="ck_customer_credit_memos_reject_trace"),
        CheckConstraint(
            "(status = 'VOIDED') = (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
            name="ck_customer_credit_memos_void_trace"),
        Index("uq_customer_credit_memos_idp_active", "inventory_disposition_order_id",
              unique=True,
              postgresql_where=text("status IN ('PENDING_APPROVAL','POSTED')")),
        Index("ix_customer_credit_memos_status_created", "status", text("created_at DESC")),
        Index("ix_customer_credit_memos_customer_created", "customer_id",
              text("created_at DESC")),
        Index("ix_customer_credit_memos_sales_created", "sales_order_id",
              text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    inventory_disposition_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inventory_disposition_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="CNY")
    memo_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=CustomerCreditMemoStatus.PENDING_APPROVAL)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_allocated: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    amount_unallocated: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), Computed("amount - amount_allocated", persisted=True))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    posted_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
