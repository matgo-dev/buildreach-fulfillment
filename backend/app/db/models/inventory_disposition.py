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


class InventoryDispositionStatus:
    PENDING_RECEIPT = "PENDING_RECEIPT"
    HELD = "HELD"
    CLOSED_WITHOUT_RECEIPT = "CLOSED_WITHOUT_RECEIPT"
    VOIDED = "VOIDED"
    ALL = (PENDING_RECEIPT, HELD, CLOSED_WITHOUT_RECEIPT, VOIDED)


class InventoryDispositionReceiptHandling:
    CLOSE_WITHOUT_RECEIPT = "CLOSE_WITHOUT_RECEIPT"
    RECEIVE_TO_DISPOSITION = "RECEIVE_TO_DISPOSITION"
    ALL = (CLOSE_WITHOUT_RECEIPT, RECEIVE_TO_DISPOSITION)


class InventoryDispositionOrder(Base, TimestampUpdateMixin):
    """库存处置单。

    客户取消但供应商侧不冲正时,用库存处置单承载库存去向:已入库货物转入待处置;
    仍在途货物要么关闭未收货,要么仍由原入库单承载到仓事实并直接进入待处置库存。
    """
    __tablename__ = "inventory_disposition_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_RECEIPT','HELD','CLOSED_WITHOUT_RECEIPT','VOIDED')",
            name="ck_inv_dispositions_status"),
        CheckConstraint(
            "receipt_handling IN ('CLOSE_WITHOUT_RECEIPT','RECEIVE_TO_DISPOSITION')",
            name="ck_inv_dispositions_receipt_handling"),
        CheckConstraint(
            "("
            "receipt_handling = 'CLOSE_WITHOUT_RECEIPT' "
            "AND status IN ('CLOSED_WITHOUT_RECEIPT','VOIDED')"
            ") OR ("
            "receipt_handling = 'RECEIVE_TO_DISPOSITION' "
            "AND status IN ('PENDING_RECEIPT','HELD','VOIDED')"
            ")",
            name="ck_inv_dispositions_status_receipt_handling"),
        CheckConstraint("purchase_currency ~ '^[A-Z]{3}$'",
                        name="ck_inv_dispositions_purchase_currency_iso4217"),
        CheckConstraint("supplier_payable_amount >= 0",
                        name="ck_inv_dispositions_supplier_payable_nn"),
        CheckConstraint(
            "status != 'HELD' OR (held_at IS NOT NULL AND held_by IS NOT NULL)",
            name="ck_inv_dispositions_held_trace_required"),
        CheckConstraint(
            "status NOT IN ('PENDING_RECEIPT','CLOSED_WITHOUT_RECEIPT') "
            "OR (held_at IS NULL AND held_by IS NULL)",
            name="ck_inv_dispositions_preheld_trace_empty"),
        CheckConstraint(
            "(status = 'VOIDED') = (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
            name="ck_inv_dispositions_void_trace"),
        Index("uq_inv_dispositions_inbound_active", "inbound_order_id", unique=True,
              postgresql_where=text("status <> 'VOIDED'")),
        Index("ix_inv_dispositions_status_created", "status", text("created_at DESC")),
        Index("ix_inv_dispositions_sales_created", "sales_order_id", text("created_at DESC")),
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
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    payable_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("payables.id", ondelete="RESTRICT"), nullable=False, index=True)
    purchase_currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=InventoryDispositionStatus.PENDING_RECEIPT)
    receipt_handling: Mapped[str] = mapped_column(String(30), nullable=False)
    supplier_payable_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    held_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    held_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class InventoryDispositionLine(Base, TimestampUpdateMixin):
    __tablename__ = "inventory_disposition_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_inv_disposition_lines_qty_pos"),
        CheckConstraint("unit_cost >= 0", name="ck_inv_disposition_lines_unit_cost_nn"),
        CheckConstraint("line_cost >= 0", name="ck_inv_disposition_lines_cost_nn"),
        CheckConstraint("sort_order >= 0", name="ck_inv_disposition_lines_sort_nn"),
        UniqueConstraint("inventory_disposition_order_id", "inbound_order_line_id",
                         name="uq_inv_disposition_lines_order_inbound_line"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inventory_disposition_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inventory_disposition_orders.id", ondelete="CASCADE"),
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
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    line_cost: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
