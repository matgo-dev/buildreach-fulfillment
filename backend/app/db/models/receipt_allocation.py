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


class AllocationType:
    """核销来源:自动(按账龄 FIFO)/ 人工(选哪张应收)。"""
    AUTO = "AUTO"
    MANUAL = "MANUAL"
    ALL = (AUTO, MANUAL)


class ReceiptAllocation(Base):
    """收款核销记录(核销层,收侧)。把一笔收款勾到一张应收款,部分核销靠 amount 不靠多行。

    反核销 = 软删留痕(reversed_at),非硬删——审计可追「这笔核销被谁何时因何撤销」。
    活动核销 = reversed_at IS NULL;不变量只算活动行。核销引擎是 receipts/receivables
    的 amount_allocated 唯一写入口(核销 +=,反核销 -=)。核销记录无单号(内部,用 id)。
    """
    __tablename__ = "receipt_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_receipt_alloc_amount_pos"),
        CheckConstraint("alloc_type IN ('AUTO','MANUAL')", name="ck_receipt_alloc_type"),
        # 偏唯一:一笔收款对一张应收至多一条**活动**核销(部分核销靠 amount);
        # 反核销留痕(reversed_at 非空)后退出偏唯一,可再建新活动行。
        Index("uq_receipt_alloc_active", "receipt_id", "receivable_id", unique=True,
              postgresql_where=text("reversed_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("receipts.id", ondelete="RESTRICT"), nullable=False, index=True)
    receivable_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("receivables.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    alloc_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # 反核销 = 软删留痕;活动 = reversed_at IS NULL。
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reversed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    reverse_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 核销操作人(自动核销 = 登记收款者)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("now()"))
