from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class QuotationStatus:
    DRAFT = "DRAFT"


class QuotationOrder(Base, TimestampUpdateMixin):
    __tablename__ = "quotation_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id"), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh")
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=QuotationStatus.DRAFT)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuotationLine(Base, TimestampUpdateMixin):
    __tablename__ = "quotation_lines"
    __table_args__ = (
        # 金额/数量 DB 兜底(应用层 Pydantic 已给干净 400,这里防直连/回归写坏数据)
        CheckConstraint("qty > 0", name="ck_qlines_qty_pos"),
        CheckConstraint("unit_price >= 0", name="ck_qlines_unit_price_nn"),
        CheckConstraint("line_total >= 0", name="ck_qlines_line_total_nn"),
        CheckConstraint("sort_order >= 0", name="ck_qlines_sort_nn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quotation_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotation_orders.id"), nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id"), nullable=False, index=True)  # 溯源
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    spec_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
