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


class ReceiptStatus:
    """收款单派生状态(不落列——UNCLAIMED 由 customer_id 决定,其余由 amount_* 决定)。schema 层输出。

    四态:UNCLAIMED(客户未知,独立于金额,不可核销)与三个核销进度态正交(契约 D1)。
    """
    UNCLAIMED = "UNCLAIMED"              # customer_id 空 = 认不出付款客户,待认领
    UNALLOCATED = "UNALLOCATED"          # 已认领·全额未核销(全额预收)
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    ALL = (UNCLAIMED, UNALLOCATED, PARTIALLY_ALLOCATED, FULLY_ALLOCATED)


def derive_receipt_status(customer_id, amount, amount_allocated) -> str:
    """单一派生口径:customer_id 空 → UNCLAIMED(客户维度,先判);否则按核销进度——
    先判分配完(allocated>=amount,含 0 金额边界,对齐账层判序、不依赖 amount>0 CHECK 撑着),
    再判未分配(<=0),之间→部分分配。判序不可倒。"""
    from decimal import Decimal
    if customer_id is None:
        return ReceiptStatus.UNCLAIMED
    amt = Decimal(str(amount))
    alloc = Decimal(str(amount_allocated))
    if alloc >= amt:
        return ReceiptStatus.FULLY_ALLOCATED
    if alloc <= 0:
        return ReceiptStatus.UNALLOCATED
    return ReceiptStatus.PARTIALLY_ALLOCATED


class Receipt(Base, TimestampUpdateMixin):
    """收款单(收侧实层)。人工登记一笔到账;核销引擎自动/人工把钱勾到应收账层。

    收付不对称(D1):customer_id **可空** = 待认领(认不出付款客户),认领后回填并核销。
    status 完全派生(customer 维 + amount_* 维),不落列。void = 纠错口(登记错作废重录,D11)。
    amount_unallocated(Computed)= 未分配余额 = 预收(§7.2),镜像账层 balance 范式。
    """
    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_receipts_currency_iso4217"),
        # 到账金额登记即定死,必 > 0(零元到账无业务意义)。
        CheckConstraint("amount > 0", name="ck_receipts_amount_pos"),
        # 已核销 ∈ [0, amount](不超分配/不负);核销引擎唯一写入口。
        CheckConstraint(
            "amount_allocated >= 0 AND amount_allocated <= amount",
            name="ck_receipts_allocated_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 单号:运营引用/审计留痕,NumberScope RECEIPT(RC{YYYYMM}{seq:04d})。
    receipt_no: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    # 可空 = 待认领(认不出付款客户);认领后回填。收付不对称:付款侧 supplier 必填。
    # 全量索引(FK 铁律,可空不影响):核销/列表按客户找单的查询路径。
    customer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=True, index=True)
    # 从哪个账户到账(自由文本;银行账户主数据 = 留白 #9,不建)。
    account_info: Mapped[str | None] = mapped_column(String(200), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    amount_allocated: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # 未分配余额 = 预收;恒等式落 DB 最强层,ORM 只读、不进 INSERT/UPDATE(镜像账层 balance)。
    amount_unallocated: Mapped[float] = mapped_column(
        Numeric(18, 2), Computed("amount - amount_allocated", persisted=True))
    received_at: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # void 轴(纠错口):非空 = 已作废,行留痕、不进列表默认聚合。
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
