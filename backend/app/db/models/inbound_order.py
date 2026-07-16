from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Date,
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


class InboundOrderStatus:
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"
    ALL = (IN_TRANSIT, RECEIVED, CANCELLED)


# 状态机单一源头(model 层常量)。入库单 = ASN:供应商发货即建(在途本身即可编辑工作态),
# 货到货代仓确认入库。无 DRAFT——「草稿=还没弄好」的语义在此不存在,不造投机态(见契约 D6)。
# RECEIVED→IN_TRANSIT = 撤销入库(守卫式纠错口,镜像出库单撤销);CANCELLED 终态。
INBOUND_ORDER_TRANSITIONS: dict[str, set[str]] = {
    InboundOrderStatus.IN_TRANSIT: {InboundOrderStatus.RECEIVED, InboundOrderStatus.CANCELLED},
    InboundOrderStatus.RECEIVED: {InboundOrderStatus.IN_TRANSIT},
    InboundOrderStatus.CANCELLED: set(),
}
# 可编辑集:仅在途(改到实收再确认)。无硬删——入库单对应真实发货事件,只作废不删。
INBOUND_ORDER_EDITABLE_STATUSES: set[str] = {InboundOrderStatus.IN_TRANSIT}
INBOUND_ORDER_DELETABLE_STATUSES: set[str] = set()


class ReceiptProgress:
    """PO 收货进度(轴2,机器派生,不落列;镜像 PurchaseProgress)。
    口径唯一(compute_received_qty),仅 RECEIVED 计入,在途不算已收。见 inbound_order_service。"""
    NOT_RECEIVED = "NOT_RECEIVED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    FULLY_RECEIVED = "FULLY_RECEIVED"
    ALL = (NOT_RECEIVED, PARTIALLY_RECEIVED, FULLY_RECEIVED)


class InboundOrder(Base, TimestampUpdateMixin):
    __tablename__ = "inbound_orders"
    __table_args__ = (
        # 状态 DB 兜底,bound 到状态机全集(单一源头 InboundOrderStatus.ALL)。
        CheckConstraint(
            "status IN ('IN_TRANSIT','RECEIVED','CANCELLED')", name="ck_inborders_status"),
        # 列表默认 status tab 过滤 + created_at DESC 排序(镜像 ix_porders_status_created)。
        Index("ix_inborders_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # 锚定 1 PO(1 PO : N 入库单,分批到货)。RESTRICT:被入库单引用的 PO 不可硬删。
    # 仅 CONFIRMED PO 可建(service 守卫);不 UNIQUE(1:N 分批)。
    purchase_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InboundOrderStatus.IN_TRANSIT)
    # 头程物流(§8:专线/手工填,无独立承运商主数据)。
    carrier_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tracking_no: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    shipped_at: Mapped["Date | None"] = mapped_column(Date, nullable=True)  # 供应商发货日
    eta: Mapped["Date | None"] = mapped_column(Date, nullable=True)          # 预计到货
    # 实际到货日;确认入库时必填(默认当天)。
    arrived_at: Mapped["Date | None"] = mapped_column(Date, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 建单人(审计归属)。确认/撤销动作走 audit_logs,不加 received_by(遵审计归属判据)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    # 无 currency / 金额列(契约 D3:入库单据零成本列,币种随 PO)。


class InboundOrderLine(Base, TimestampUpdateMixin):
    __tablename__ = "inbound_order_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_inblines_qty_pos"),
        CheckConstraint("sort_order >= 0", name="ck_inblines_sort_nn"),
        # 一次收货事件同一 PO 行至多一行(不堆两行同 SKU);跨单分批由 service 守卫。
        # 分工同 uq_plines_po_soline:结构性单行 DB 兜底,跨单累计超收走 service。
        UniqueConstraint(
            "inbound_order_id", "purchase_order_line_id", name="uq_inblines_inb_poline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 行是单的组合成分:单删则行随删(CASCADE)。
    inbound_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbound_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    # 行级 document flow(quota 聚合查询路径,必须有索引)。RESTRICT:被引用的 PO 行不可硬删。
    purchase_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_order_lines.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)  # 溯源
    # 平移自 PO 行快照(收的就是订的,不回读 SKU)。
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    spec_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    # 本次入库数量(在途可改,RECEIVED 冻结)。无 unit_price / line_total 列(契约 D3)。
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)  # 行级异常备注(破损等)
