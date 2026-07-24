from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class PaymentStatus:
    """付款单派生状态(不落列——由 amount_* 决定)。schema 层输出。

    三态:无 UNCLAIMED(D1 不对称——付款是我方主动付给已知供应商,supplier 必填,无待认领)。
    """
    UNALLOCATED = "UNALLOCATED"          # 全额未核销(全额预付)
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    ALL = (UNALLOCATED, PARTIALLY_ALLOCATED, FULLY_ALLOCATED)


def derive_payment_status(amount, amount_allocated) -> str:
    """单一派生口径(边界共用 _settlement,与 payment_service._STATUS_CONDS 同源不双写):
    进度三态,无 UNCLAIMED。先判分配完(含 0 金额边界),再判未分配,之间→部分分配。"""
    from decimal import Decimal

    from app.db.models._settlement import is_fully_settled, is_unsettled
    amt = Decimal(str(amount))
    alloc = Decimal(str(amount_allocated))
    if is_fully_settled(amt, alloc):
        return PaymentStatus.FULLY_ALLOCATED
    if is_unsettled(amt, alloc):
        return PaymentStatus.UNALLOCATED
    return PaymentStatus.PARTIALLY_ALLOCATED


class Payment(Base, TimestampUpdateMixin):
    """付款单(付侧实层)。人工登记一笔付款;核销引擎把钱勾到应付账层。🔴红线域。

    结构对称 receipts,差异:supplier_id 必填(D1 无待认领态)、paid_at(付款日 ≠ 到账日,P2②)。
    预付款(付款侧未分配余额)P0 支持(对称预收):amount_unallocated>0 即预付,留存不丢。
    🔴 关联供应商 + 承载采购付款金额 → 端点级 payment:read/manage 门控,与收侧不共可见性。
    """
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payments_currency_iso4217"),
        CheckConstraint("amount > 0", name="ck_payments_amount_pos"),
        CheckConstraint(
            "amount_allocated >= 0 AND amount_allocated <= amount",
            name="ck_payments_allocated_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 单号:NumberScope PAYMENT(PM{YYYYMM}{seq:04d})。
    payment_no: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    # 🔴 必填(D1 不对称:主动付给已知供应商,无待认领)。全量索引(FK 铁律)。
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    # 付款走哪个账户出(自由文本)。
    account_info: Mapped[str | None] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    amount_allocated: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # 未分配余额 = 预付;恒等式落 DB(镜像账层 balance / 收侧 amount_unallocated)。
    amount_unallocated: Mapped[float] = mapped_column(
        Numeric(18, 2), Computed("amount - amount_allocated", persisted=True))
    # 付款日/出账日(≠ 收侧 received_at 到账日,语义不同不照抄列名,P2②)。
    paid_at: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
