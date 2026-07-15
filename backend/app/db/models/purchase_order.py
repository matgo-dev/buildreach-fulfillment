from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
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


class PurchaseOrderStatus:
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    ALL = (DRAFT, CONFIRMED, CANCELLED)


# 状态机单一源头(model 层常量)。轴1=单据生命周期,人驱动管门禁。
# DRAFT→CONFIRMED(下单)→CANCELLED;DRAFT 可直接取消。不设 SENT(按单直采并入);
# RECEIVED/部分到货留入库步开 CONFIRMED 出边,不预造投机态。
PURCHASE_ORDER_TRANSITIONS: dict[str, set[str]] = {
    PurchaseOrderStatus.DRAFT: {PurchaseOrderStatus.CONFIRMED, PurchaseOrderStatus.CANCELLED},
    PurchaseOrderStatus.CONFIRMED: {PurchaseOrderStatus.CANCELLED},
    PurchaseOrderStatus.CANCELLED: set(),
}
# 可编辑集 / 可硬删集:仅草稿(同报价)。CONFIRMED 已向供应商下单,锁定只能取消。
PURCHASE_ORDER_EDITABLE_STATUSES: set[str] = {PurchaseOrderStatus.DRAFT}
PURCHASE_ORDER_DELETABLE_STATUSES: set[str] = {PurchaseOrderStatus.DRAFT}


class PurchaseProgress:
    """采购进度(轴2,机器派生,不落列)。SO 每行 covered_qty 汇总 → 整单进度。
    计算口径唯一(compute_covered_qty),守卫与展示共用,见 purchase_order_service。"""
    NOT_ORDERED = "NOT_ORDERED"
    PARTIALLY_ORDERED = "PARTIALLY_ORDERED"
    FULLY_ORDERED = "FULLY_ORDERED"
    ALL = (NOT_ORDERED, PARTIALLY_ORDERED, FULLY_ORDERED)


class PurchaseOrder(Base, TimestampUpdateMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        # 状态 DB 兜底,bound 到状态机全集(单一源头 PurchaseOrderStatus.ALL)。
        CheckConstraint(
            "status IN ('DRAFT','CONFIRMED','CANCELLED')", name="ck_porders_status"),
        # 采购币种存 ISO4217 三字母大写 code;DB 锁死格式,展示走 i18n。
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_porders_currency_iso4217"),
        # 🔴红线:采购金额合计 = Σ line_total;DB 兜底非负。
        CheckConstraint("total_amount >= 0", name="ck_porders_total_amount_nn"),
        # 列表默认 status tab 过滤 + created_at DESC 排序(镜像 sales_orders ix_sorders_status_created)。
        Index("ix_porders_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # 来源销售单:下游记来源(SAP document flow / Odoo origin)。RESTRICT:被 PO 引用时 SO 不可硬删。
    # 不 UNIQUE:SO:PO=1:N(一 SO 可按供应商拆多张 PO)。
    source_sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    # 一张 PO 一个供应商(拆单轴)。RESTRICT:被 PO 引用的供应商不可硬删。
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PurchaseOrderStatus.DRAFT)
    # 🔴红线:采购金额合计 = Σ line_total(采购价属成本域,对无 read_cost 者响应置 null)。
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 建单采购员(审计归属)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class PurchaseOrderLine(Base, TimestampUpdateMixin):
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        # 金额/数量/排序 DB 兜底(镜像 sales_order_lines)。
        CheckConstraint("qty > 0", name="ck_plines_qty_pos"),
        CheckConstraint("unit_price >= 0", name="ck_plines_unit_price_nn"),
        CheckConstraint("line_total >= 0", name="ck_plines_line_total_nn"),
        CheckConstraint("sort_order >= 0", name="ck_plines_sort_nn"),
        # 同一张 PO 内同一 SO 行至多一行(一次下单事件不堆两行同 SKU)。
        # 在最强层挡住「一个 payload 重复提交同一 so_line、逐行不超但合计超采」;
        # 跨 PO(不同 po_id)累计超采由 service 守卫负责(两者分工,见 service 注释)。
        UniqueConstraint(
            "purchase_order_id", "source_sales_order_line_id", name="uq_plines_po_soline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 行是 PO 的组合成分:单删则行随删(CASCADE)。
    purchase_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)  # 溯源
    # 行级 document flow(SAP item-level 追溯)。RESTRICT:被 PO 行引用的 SO 行不可硬删。
    # 不单列 UNIQUE:跨 PO 允许同一 SO 行分批/分供应商/取消后重下(与转销售 1:1 硬 UNIQUE 故意不同);
    # 入复合 UNIQUE(见 __table_args__)= PO 内唯一。
    source_sales_order_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_order_lines.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    # 平移自 SO 行快照(建单时冻结)。行草稿可改数量/价(非 write-once),故 TimestampUpdateMixin。
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    spec_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    # 🔴红线:采购单价(默认 sku.reference_price,采购员可改)。
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    # 🔴红线:unit_price × qty(精度口径见 service)。
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
