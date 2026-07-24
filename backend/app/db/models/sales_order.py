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

from app.db.base import Base, TimestampMixin, TimestampUpdateMixin


class SalesOrderStatus:
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    ALL = (CONFIRMED, CANCELLED)


# 状态机单一源头(model 层常量)。整单取消:CONFIRMED→CANCELLED(终态,不复活——
# 要继续做生意 → 报价回 LOCKED 重转新 SO);取消前置守卫 = 下游无活动 PO(service 层 41802)。
# 更多态(→采购中…)留给后续增量系统性做对,不预造投机态。
SALES_ORDER_TRANSITIONS: dict[str, set[str]] = {
    SalesOrderStatus.CONFIRMED: {SalesOrderStatus.CANCELLED},
    SalesOrderStatus.CANCELLED: set(),
}


class SalesOrder(Base, TimestampUpdateMixin):
    __tablename__ = "sales_orders"
    __table_args__ = (
        # 币种存 ISO4217 三字母大写 code(复制自报价);DB 锁死格式,展示走 i18n。
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_sorders_currency_iso4217"),
        # 状态 DB 兜底,bound 到状态机全集(单一源头 SalesOrderStatus.ALL)。
        CheckConstraint("status IN ('CONFIRMED','CANCELLED')", name="ck_sorders_status"),
        # 表头总额转换时冻结自报价 total;DB 兜底非负。
        CheckConstraint("total_amount >= 0", name="ck_sorders_total_amount_nn"),
        # 取消留痕轴与状态一致性锁死在 DB(偏唯一谓词只看 status,防两轴漂移脏审计)。
        CheckConstraint("(status = 'CANCELLED') = (cancelled_at IS NOT NULL)",
                        name="ck_sorders_cancel_trace"),
        # 列表默认 status tab 过滤 + created_at DESC 排序(镜像报价 ix_qorders_status_created)。
        Index("ix_sorders_status_created", "status", text("created_at DESC")),
        # 「一报价 ≤ 一**活动**销售单」:偏唯一只约束非取消行——取消后报价回 LOCKED 可重转,
        # 新活动行与 CANCELLED 留痕行共存(同款先例 uq_payables_inbound_active)。
        Index("uq_sorders_source_quotation_active", "source_quotation_id", unique=True,
              postgresql_where=text("status <> 'CANCELLED'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # 来源报价:下游记来源(Odoo origin / NetSuite createdFrom / SAP document flow 通行)。
    # 「一报价≤一活动销售单、不重复转」由活动行偏唯一硬保证(见 __table_args__);
    # 全量索引服务 FK 侧查找与含取消行的溯源(FK 列全量索引默认加,偏唯一不算替代)。
    source_quotation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotation_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
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
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    # 取消留痕轴(镜像 payable void 轴):非空 = 已取消;与 status 一致性由 CHECK 锁死。
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SalesOrderLine(Base, TimestampMixin):
    __tablename__ = "sales_order_lines"
    __table_args__ = (
        # 金额/数量/排序 DB 兜底(镜像 quotation_lines)。
        CheckConstraint("qty > 0", name="ck_slines_qty_pos"),
        CheckConstraint("unit_price >= 0", name="ck_slines_unit_price_nn"),
        CheckConstraint("line_total >= 0", name="ck_slines_line_total_nn"),
        CheckConstraint("sort_order >= 0", name="ck_slines_sort_nn"),
        CheckConstraint("covered_qty >= 0", name="ck_slines_covered_nn"),
        # 同单内每报价行只入一次(挡复制逻辑 bug 的行级重复);跨单放行——取消后重转的
        # 新 SO 复用同批报价行(原单列 UNIQUE 会挡重转,故降为复合)。
        Index("uq_slines_order_source_line", "sales_order_id", "source_quotation_line_id",
              unique=True),
        # 一 SKU 一价公理(无阶梯价):同销售单同 SKU 至多一行(报价转单继承)。
        # 单一源头落 DB,与 migration 0024 同名。
        UniqueConstraint("sales_order_id", "sku_id", name="uq_slines_order_sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 行是销售单的组合成分:单删则行随删(CASCADE);sku 是溯源引用不可硬删(RESTRICT)。
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)  # 溯源
    # 行级 document flow(SAP item-level 追溯);同单内唯一性见复合 UNIQUE(__table_args__)。
    # 单列全量索引服务 FK 侧查找(报价删行守卫等;复合索引右列不覆盖自身查找)。
    source_quotation_line_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotation_lines.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    # 业务/快照字段 write-once(平移报价行冻结快照,转换时不重算)→ TimestampMixin(仅 created_at),
    # 变更历史归 audit_logs;与 QuotationLine(草稿期可变→UpdateMixin)按真实可变性分叉。
    # 例外:covered_qty 是系统维护可变列(采购写入口重算刷新,非用户编辑),不进 SO 行时间戳
    # ——其变更审计归属 PO 侧动作(create/save/cancel),见 purchase_order_service。
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    spec_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    # 已覆盖量物化列 = Σ(非 CANCELLED PO 行 qty,含 DRAFT)。compute_covered_qty 是唯一计算口径,
    # 本列是它的同事务物化缓存(采购三写入口在持 FOR UPDATE 锁下重算写回,重算非自增)。
    # 列表进度徽标/筛选由本列在 SQL 派生;守卫/详情仍读实时 compute_covered_qty(不信缓存)。
    covered_qty: Mapped[float] = mapped_column(
        Numeric(18, 3), nullable=False, server_default="0", default=0)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
