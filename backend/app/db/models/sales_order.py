from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, TimestampUpdateMixin


class SalesOrderStatus:
    CONFIRMED = "CONFIRMED"
    ALL = (CONFIRMED,)


# 状态机单一源头(model 层常量)。本增量销售单只建初始态 CONFIRMED、无出边;
# 完整 SO 状态机(→采购中…)留给「转采购」增量再系统性做对,不预造投机态。
SALES_ORDER_TRANSITIONS: dict[str, set[str]] = {
    SalesOrderStatus.CONFIRMED: set(),
}


class SalesOrder(Base, TimestampUpdateMixin):
    __tablename__ = "sales_orders"
    __table_args__ = (
        # 币种存 ISO4217 三字母大写 code(复制自报价);DB 锁死格式,展示走 i18n。
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_sorders_currency_iso4217"),
        # 状态 DB 兜底,bound 到状态机全集(单一源头 SalesOrderStatus.ALL)。
        CheckConstraint("status IN ('CONFIRMED')", name="ck_sorders_status"),
        # 表头总额转换时冻结自报价 total;DB 兜底非负。
        CheckConstraint("total_amount >= 0", name="ck_sorders_total_amount_nn"),
        # 列表默认 status tab 过滤 + created_at DESC 排序(镜像报价 ix_qorders_status_created)。
        Index("ix_sorders_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # 来源报价:下游记来源(Odoo origin / NetSuite createdFrom / SAP document flow 通行)。
    # UNIQUE 在最强层硬保证「一报价≤一销售单、不重复转」;唯一索引兼作反查(报价→销售单)路径。
    source_quotation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotation_orders.id", ondelete="RESTRICT"),
        nullable=False, unique=True)
    # ON DELETE RESTRICT:客户/报价人被销售单引用时不可硬删(同报价口径)。
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    # 报价人(业务归属):复制自报价 salesperson_id;与 created_by(谁执行转换)不同语义。
    salesperson_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SalesOrderStatus.CONFIRMED)
    # 表头总额 = 转换时报价 total 的冻结拷贝(销售单是下游唯一真值源)。
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(String(180), nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 执行转换的人(审计归属);可 ≠ salesperson_id(报价业务归属,复制自报价)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)


class SalesOrderLine(Base, TimestampMixin):
    __tablename__ = "sales_order_lines"
    __table_args__ = (
        # 金额/数量/排序 DB 兜底(镜像 quotation_lines)。
        CheckConstraint("qty > 0", name="ck_slines_qty_pos"),
        CheckConstraint("unit_price >= 0", name="ck_slines_unit_price_nn"),
        CheckConstraint("line_total >= 0", name="ck_slines_line_total_nn"),
        CheckConstraint("sort_order >= 0", name="ck_slines_sort_nn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 行是销售单的组合成分:单删则行随删(CASCADE);sku 是溯源引用不可硬删(RESTRICT)。
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)  # 溯源
    # 行级 document flow(SAP item-level 追溯);整单 1:1 下每报价行只应入单一次,
    # UNIQUE 在最强层挡住复制逻辑 bug 把同一报价行重复写入(order 级 UNIQUE 挡不住行级重复)。
    source_quotation_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotation_lines.id", ondelete="RESTRICT"),
        nullable=False, unique=True)
    # 平移报价行已冻结快照(转换时不重算)。行 write-once → TimestampMixin(仅 created_at),
    # 变更历史归 audit_logs;与 QuotationLine(草稿期可变→UpdateMixin)按真实可变性分叉。
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    spec_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
