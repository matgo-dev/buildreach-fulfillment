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


class ReverseRequestType:
    """逆向申请类型。MVP-1 只开放出库前履约中取消,表名预留后续售后复用。"""

    FULFILLMENT_CANCEL = "FULFILLMENT_CANCEL"
    ALL = (FULFILLMENT_CANCEL,)


class ReverseRequestStatus:
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    ALL = (PENDING_REVIEW, APPROVED, REJECTED, COMPLETED)


REVERSE_REQUEST_TRANSITIONS: dict[str, set[str]] = {
    ReverseRequestStatus.PENDING_REVIEW: {
        ReverseRequestStatus.APPROVED,
        ReverseRequestStatus.REJECTED,
    },
    ReverseRequestStatus.APPROVED: {ReverseRequestStatus.COMPLETED},
    ReverseRequestStatus.REJECTED: set(),
    ReverseRequestStatus.COMPLETED: set(),
}


class ReverseGoodsStatus:
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    ALL = (IN_TRANSIT, RECEIVED)


class ReverseSupplierResolution:
    """供应商处理结论。REJECT_CONTINUE 走驳回,不落 APPROVED 态。"""

    SUPPLIER_ACCEPTS_RETURN = "SUPPLIER_ACCEPTS_RETURN"
    COMPANY_BEAR_LOSS = "COMPANY_BEAR_LOSS"
    ALL = (SUPPLIER_ACCEPTS_RETURN, COMPANY_BEAR_LOSS)


class ReverseRequest(Base, TimestampUpdateMixin):
    __tablename__ = "reverse_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('FULFILLMENT_CANCEL')",
            name="ck_reverse_requests_type",
        ),
        CheckConstraint(
            "status IN ('PENDING_REVIEW','APPROVED','REJECTED','COMPLETED')",
            name="ck_reverse_requests_status",
        ),
        CheckConstraint(
            "goods_status IN ('IN_TRANSIT','RECEIVED')",
            name="ck_reverse_requests_goods_status",
        ),
        CheckConstraint(
            "supplier_resolution IS NULL OR supplier_resolution IN "
            "('SUPPLIER_ACCEPTS_RETURN','COMPANY_BEAR_LOSS')",
            name="ck_reverse_requests_supplier_resolution",
        ),
        CheckConstraint(
            "(status IN ('APPROVED','COMPLETED')) = (supplier_resolution IS NOT NULL)",
            name="ck_reverse_requests_resolution_required",
        ),
        Index("ix_reverse_requests_status_created", "status", text("created_at DESC")),
        Index("ix_reverse_requests_so_created", "sales_order_id", text("created_at DESC")),
        Index(
            "uq_reverse_requests_inbound_active",
            "inbound_order_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING_REVIEW','APPROVED')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ReverseRequestStatus.PENDING_REVIEW)

    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    purchase_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    inbound_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbound_orders.id", ondelete="RESTRICT"), nullable=False, index=True)

    goods_status: Mapped[str] = mapped_column(String(20), nullable=False)
    supplier_resolution: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    requested_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    completion_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReverseRequestLine(Base):
    __tablename__ = "reverse_request_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_reverse_request_lines_qty_pos"),
        UniqueConstraint("reverse_request_id", "inbound_order_line_id",
                         name="uq_reverse_request_lines_request_inbline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reverse_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reverse_requests.id", ondelete="CASCADE"),
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
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
