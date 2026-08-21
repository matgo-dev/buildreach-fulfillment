from __future__ import annotations

from datetime import datetime

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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, TimestampUpdateMixin


class InventoryMovementType:
    INBOUND_RECEIVE = "INBOUND_RECEIVE"
    INBOUND_UNRECEIVE = "INBOUND_UNRECEIVE"
    OUTBOUND_ISSUE = "OUTBOUND_ISSUE"
    PURCHASE_RETURN_ISSUE = "PURCHASE_RETURN_ISSUE"
    DISPOSITION_HOLD = "DISPOSITION_HOLD"
    ALL = (
        INBOUND_RECEIVE,
        INBOUND_UNRECEIVE,
        OUTBOUND_ISSUE,
        PURCHASE_RETURN_ISSUE,
        DISPOSITION_HOLD,
    )


class InventorySourceType:
    INBOUND_ORDER = "INBOUND_ORDER"
    OUTBOUND_ORDER = "OUTBOUND_ORDER"
    PURCHASE_RETURN_ORDER = "PURCHASE_RETURN_ORDER"
    INVENTORY_DISPOSITION_ORDER = "INVENTORY_DISPOSITION_ORDER"
    ALL = (
        INBOUND_ORDER,
        OUTBOUND_ORDER,
        PURCHASE_RETURN_ORDER,
        INVENTORY_DISPOSITION_ORDER,
    )


class InventoryBalance(Base, TimestampUpdateMixin):
    """销售单维度库存余额。

    当前系统没有自由库存:每一份库存仍归属一个 sales_order_id。本表只是把原实时聚合口径
    物化落库,供库存页和出库校验读取。
    """
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("sales_order_id", "sku_id", name="uq_inventory_balances_so_sku"),
        CheckConstraint("inbound_qty >= 0", name="ck_inventory_balances_inbound_nn"),
        CheckConstraint("outbound_qty >= 0", name="ck_inventory_balances_outbound_nn"),
        CheckConstraint("disposition_qty >= 0", name="ck_inventory_balances_disposition_nn"),
        CheckConstraint("inbound_qty >= outbound_qty + disposition_qty",
                        name="ck_inventory_balances_available_nn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"),
        nullable=False)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)
    inbound_qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    outbound_qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    disposition_qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False, default=0)
    available_qty: Mapped[float] = mapped_column(
        Numeric(18, 3), Computed("inbound_qty - outbound_qty - disposition_qty", persisted=True))


class InventoryMovement(Base, TimestampMixin):
    """库存流水。

    movement_type 表达业务动作,qty_delta 表达可发库存方向:入库为正,出库/撤销入库为负。
    DISPOSITION_HOLD 是可发口径重分类,物理库存仍由 inbound_qty/disposition_qty 同时表达。
    source_* 指回真实业务单据,后续供应商退货/客户退货/处置单据可以继续复用这张事实表。
    """
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ("
            "'INBOUND_RECEIVE','INBOUND_UNRECEIVE','OUTBOUND_ISSUE',"
            "'PURCHASE_RETURN_ISSUE','DISPOSITION_HOLD')",
            name="ck_inventory_movements_type"),
        CheckConstraint(
            "source_type IN ('INBOUND_ORDER','OUTBOUND_ORDER','PURCHASE_RETURN_ORDER',"
            "'INVENTORY_DISPOSITION_ORDER')",
            name="ck_inventory_movements_source_type"),
        CheckConstraint("qty_delta <> 0", name="ck_inventory_movements_qty_nonzero"),
        Index("ix_inventory_movements_so_sku_occurred", "sales_order_id", "sku_id",
              text("occurred_at DESC"), text("id DESC")),
        Index("ix_inventory_movements_source", "source_type", "source_id", "movement_type", "id"),
        Index("ix_inventory_movements_source_line", "source_type", "source_line_id",
              "movement_type", "id"),
        Index("ix_inventory_movements_type_occurred", "movement_type",
              text("occurred_at DESC"), text("id DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_line_id: Mapped[int] = mapped_column(Integer, nullable=False)
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"),
        nullable=False)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)
    qty_delta: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
