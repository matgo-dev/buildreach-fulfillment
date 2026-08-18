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


class PurchaseReturnStatus:
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    VOIDED = "VOIDED"
    ALL = (PENDING_APPROVAL, APPROVED, REJECTED, RETURNED, VOIDED)


class PurchaseReturnOrder(Base, TimestampUpdateMixin):
    """采购退货单。

    采购侧真实逆向单据:把已入库、仍归属销售单的库存退回供应商。单据审批只代表业务同意
    退回;库存扣减发生在退货出库确认;应付冲销由供应商贷项单财务过账承载。
    """
    __tablename__ = "purchase_return_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_APPROVAL','APPROVED','REJECTED','RETURNED','VOIDED')",
            name="ck_preturns_status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_preturns_currency_iso4217"),
        CheckConstraint("total_amount >= 0", name="ck_preturns_total_amount_nn"),
        Index("ix_preturns_status_created", "status", text("created_at DESC")),
        Index("ix_preturns_inbound_created", "inbound_order_id", text("created_at DESC")),
        Index("ix_preturns_purchase_created", "purchase_order_id", text("created_at DESC")),
        Index("ix_preturns_supplier_created", "supplier_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    inbound_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbound_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PurchaseReturnStatus.PENDING_APPROVAL)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    returned_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    return_shipment_reference: Mapped[str | None] = mapped_column(String(80), nullable=True)
    return_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class PurchaseReturnLine(Base, TimestampUpdateMixin):
    __tablename__ = "purchase_return_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_preturn_lines_qty_pos"),
        CheckConstraint("unit_price >= 0", name="ck_preturn_lines_unit_price_nn"),
        CheckConstraint("line_total >= 0", name="ck_preturn_lines_total_nn"),
        CheckConstraint("sort_order >= 0", name="ck_preturn_lines_sort_nn"),
        UniqueConstraint(
            "purchase_return_order_id", "inbound_order_line_id",
            name="uq_preturn_lines_order_inbound_line"),
        Index("ix_preturn_lines_inbound_line_created",
              "inbound_order_line_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_return_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_return_orders.id", ondelete="CASCADE"),
        nullable=False, index=True)
    inbound_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbound_order_lines.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    purchase_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    spec_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
