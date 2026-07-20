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


class OutboundOrderStatus:
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CANCELLED = "CANCELLED"
    ALL = (DRAFT, ISSUED, CANCELLED)


# 状态机单一源头(model 层常量,镜像入库单)。出库单 = 销售单×柜双锚定的桥。
# DRAFT→{ISSUED,CANCELLED}:草稿确认出库(唯一扣库存事件)/ 草稿取消;
# ISSUED→{DRAFT}:撤销出库(守卫式纠错口,库存派生自然恢复;发运步装船后追加「柜已装船不可撤」守卫);
# CANCELLED 终态。
OUTBOUND_ORDER_TRANSITIONS: dict[str, set[str]] = {
    OutboundOrderStatus.DRAFT: {OutboundOrderStatus.ISSUED, OutboundOrderStatus.CANCELLED},
    OutboundOrderStatus.ISSUED: {OutboundOrderStatus.DRAFT},
    OutboundOrderStatus.CANCELLED: set(),
}
# 可编辑集:仅草稿(整单保存)。无硬删——草稿态取消即可,出库单锚定真实出库意图。
OUTBOUND_ORDER_EDITABLE_STATUSES: set[str] = {OutboundOrderStatus.DRAFT}


class OutboundOrder(Base, TimestampUpdateMixin):
    """出库单头。销售单 N:1 × 发运单(柜)N:1;行不跨 SO、不跨柜。
    纯仓单:无价格/成本/售价列(红线天然隔离);售价侧在应收(receivables)。"""
    __tablename__ = "outbound_orders"
    __table_args__ = (
        # 状态 DB 兜底,bound 到状态机全集(单一源头 OutboundOrderStatus.ALL)。
        CheckConstraint(
            "status IN ('DRAFT','ISSUED','CANCELLED')", name="ck_oborders_status"),
        # 列表默认 status tab 过滤 + created_at DESC 排序(镜像 ix_inborders_status_created)。
        Index("ix_oborders_status_created", "status", text("created_at DESC")),
        # 「一柜内每来源 SO 各一张」落 DB 最强层:偏唯一只约束活动行(取消行退出,可重开)。
        Index("uq_oborders_shipment_so_active", "shipment_id", "sales_order_id",
              unique=True, postgresql_where=text("status <> 'CANCELLED'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # 锚定 1 SO(行不跨 SO)。RESTRICT:被出库单引用的 SO 不可硬删。全量索引(FK 默认加)+
    # 上方偏唯一并存(用途不同)。
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    # 锚定 1 柜(行不跨柜)。RESTRICT:被出库单引用的柜不可硬删。
    shipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shipment_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OutboundOrderStatus.DRAFT)
    # 确认置、撤销清(镜像入库 arrived_at 语义:确认出库=扣库存时刻)。
    issued_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 建单人(审计归属);确认/撤销/取消动作走 audit_logs,不加 issued_by/updated_by(审计归属判据)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)


class OutboundOrderLine(Base, TimestampUpdateMixin):
    """出库单行(镜像入库行)。**不复制快照**:展示经 join SO 行的 name/spec/unit
    (SO 行确认后冻结,快照单一源头已在 SO 行;再抄一份即双源头)。"""
    __tablename__ = "outbound_order_lines"
    __table_args__ = (
        CheckConstraint("qty > 0", name="ck_oblines_qty_pos"),
        # 同单同 SO 行至多一行(镜像入库行 uq_inblines_inb_poline)。
        UniqueConstraint("outbound_order_id", "sales_order_line_id", name="uq_oblines_ob_soline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 行是单的组合成分:单删则行随删(CASCADE)。
    outbound_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("outbound_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    # 行级 document flow(可发聚合查询路径,必须有索引)。RESTRICT:被引用的 SO 行不可硬删。
    # service 守卫:必须属于头上的 SO(41903)。
    sales_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_order_lines.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    # 冗余承载派生聚合路径(compute_stock_balance outbound 臂按 (so, sku) 聚合);
    # service 守卫 = SO 行 sku 一致。RESTRICT 溯源。
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
