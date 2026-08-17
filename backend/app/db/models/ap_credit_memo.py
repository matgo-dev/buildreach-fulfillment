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


class APCreditMemoStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    POSTED = "POSTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"
    ALL = (PENDING_APPROVAL, POSTED, REJECTED, VOIDED)


class APCreditMemoType:
    PURCHASE_RETURN = "PURCHASE_RETURN"
    ALL = (PURCHASE_RETURN,)


class APCreditMemo(Base, TimestampMixin):
    """供应商贷项单 / AP Credit Memo。

    用于承载供应商侧贷项事实。采购退货出库完成后生成待财务审核的贷项单;财务过账后才
    冲减应付款未结金额。
    """
    __tablename__ = "ap_credit_memos"
    __table_args__ = (
        CheckConstraint(
            "memo_type IN ('PURCHASE_RETURN')",
            name="ck_ap_credit_memos_type"),
        CheckConstraint(
            "status IN ('PENDING_APPROVAL','POSTED','REJECTED','VOIDED')",
            name="ck_ap_credit_memos_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_ap_credit_memos_currency_iso4217"),
        CheckConstraint("amount > 0", name="ck_ap_credit_memos_amount_pos"),
        Index("uq_ap_credit_memos_preturn_active", "purchase_return_order_id", unique=True,
              postgresql_where=text("status != 'VOIDED'")),
        Index("ix_ap_credit_memos_status_created", "status", text("created_at DESC")),
        Index("ix_ap_credit_memos_payable_created", "payable_id", text("created_at DESC")),
        Index("ix_ap_credit_memos_supplier_created", "supplier_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    payable_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payables.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    purchase_return_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_return_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    memo_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=APCreditMemoStatus.PENDING_APPROVAL)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
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
