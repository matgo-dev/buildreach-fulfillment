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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class CustomerReturnStatus:
    RECEIVED = "RECEIVED"
    VOIDED = "VOIDED"
    ALL = (RECEIVED, VOIDED)


class CustomerReturnOrder(Base, TimestampUpdateMixin):
    """客户退货单。

    出库后售后入口:原出库/应收不撤销,退回货只进入售后待处置库存。
    后续退款、供应商是否接受、公司损失等财务结论挂在本单之后逐步补。
    """
    __tablename__ = "customer_return_orders"
    __table_args__ = (
        CheckConstraint("status IN ('RECEIVED','VOIDED')", name="ck_customer_returns_status"),
        CheckConstraint(
            "status != 'RECEIVED' OR (received_at IS NOT NULL AND received_by IS NOT NULL)",
            name="ck_customer_returns_receive_trace"),
        CheckConstraint(
            "(status = 'VOIDED') = (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
            name="ck_customer_returns_void_trace"),
        Index("ix_customer_returns_outbound_created", "outbound_order_id", text("created_at DESC")),
        Index("ix_customer_returns_sales_created", "sales_order_id", text("created_at DESC")),
        Index("ix_customer_returns_customer_created", "customer_id", text("created_at DESC")),
        Index("ix_customer_returns_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    outbound_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("outbound_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=CustomerReturnStatus.RECEIVED)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    received_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)


class CustomerReturnLine(Base, TimestampUpdateMixin):
    __tablename__ = "customer_return_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_customer_return_lines_qty_pos"),
        CheckConstraint("sort_order >= 0", name="ck_customer_return_lines_sort_nn"),
        UniqueConstraint(
            "customer_return_order_id", "outbound_order_line_id",
            name="uq_customer_return_lines_order_outbound_line"),
        Index("ix_customer_return_lines_outbound_line_created",
              "outbound_order_line_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_return_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customer_return_orders.id", ondelete="CASCADE"),
        nullable=False, index=True)
    outbound_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("outbound_order_lines.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    sales_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_order_lines.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    spec_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
