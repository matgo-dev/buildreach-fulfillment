from __future__ import annotations

from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class QuotationStatus:
    DRAFT = "DRAFT"


class QuotationOrder(Base, TimestampUpdateMixin):
    __tablename__ = "quotation_orders"
    __table_args__ = (
        # 币种存 ISO4217 三字母大写 code(USD/CNY…),不存中文/自由串;DB 锁死格式,展示走 i18n。
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_qorders_currency_iso4217"),
        # 状态 DB 兜底,只 bound 到当前已存在的值(同 skus 纪律);M2 增 LOCKED/CONVERTED 时同步扩这里。
        CheckConstraint("status IN ('DRAFT')", name="ck_qorders_status"),
        # 报价语言三选一(单一源头 core.languages);派生自 customer.quote_language,不手录。
        CheckConstraint("language IN ('zh','en','sw')", name="ck_qorders_language"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # ON DELETE RESTRICT 显式:客户被报价单引用时不可硬删(同 skus.unit/spu_id 口径)。
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh")
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=QuotationStatus.DRAFT)
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuotationLine(Base, TimestampUpdateMixin):
    __tablename__ = "quotation_lines"
    __table_args__ = (
        # 金额/数量 DB 兜底(应用层 Pydantic 已给干净 400,这里防直连/回归写坏数据)
        CheckConstraint("qty > 0", name="ck_qlines_qty_pos"),
        CheckConstraint("unit_price >= 0", name="ck_qlines_unit_price_nn"),
        CheckConstraint("line_total >= 0", name="ck_qlines_line_total_nn"),
        CheckConstraint("sort_order >= 0", name="ck_qlines_sort_nn"),
        # 报价语言三选一(单一源头 core.languages);继承 order.language,不手录。
        CheckConstraint("language IN ('zh','en','sw')", name="ck_qlines_language"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 报价行是报价单的组合成分:单删则行随删(CASCADE);sku 是溯源引用,不可硬删(RESTRICT)。
    quotation_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("quotation_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    sku_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("skus.id", ondelete="RESTRICT"), nullable=False, index=True)  # 溯源
    name_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    spec_text_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    qty: Mapped[float] = mapped_column(Numeric(18, 3), nullable=False)
    line_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
