from __future__ import annotations

from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class QuotationStatus:
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    CONVERTED = "CONVERTED"
    VOID = "VOID"
    ALL = (DRAFT, LOCKED, CONVERTED, VOID)


# 状态机单一源头(model 层常量;service 守卫 + 前端镜像均派生自此,不并列副本)。
# 合法转移矩阵:草稿↔锁档、锁档→转销售、草稿/锁档→作废、已转→锁档(仅 SO 取消回退);
# 作废为终态。CONVERTED→LOCKED 是真实存在的转移故进矩阵,但**仅限 SO 取消服务内部走**——
# 公开 lock 端点已显式收紧仅 DRAFT(lock_order),防止绕过 SO 取消守卫拉回已转报价。
QUOTATION_TRANSITIONS: dict[str, set[str]] = {
    QuotationStatus.DRAFT: {QuotationStatus.LOCKED, QuotationStatus.VOID},
    QuotationStatus.LOCKED: {QuotationStatus.DRAFT, QuotationStatus.CONVERTED, QuotationStatus.VOID},
    QuotationStatus.CONVERTED: {QuotationStatus.LOCKED},
    QuotationStatus.VOID: set(),
}
# 编辑/删除仅草稿(锁档后只读;草稿=从没弄好可硬删)——"能否 PUT/硬删"不是状态转移,
# 矩阵推不出,故各自独立常量(独立事实,非并列副本)。
QUOTATION_EDITABLE: set[str] = {QuotationStatus.DRAFT}
QUOTATION_DELETABLE: set[str] = {QuotationStatus.DRAFT}
# 可作废集相反:作废本身是一条转移,该事实矩阵已拥有,故**派生**自矩阵(目标含 VOID 的态),
# 不另立并列副本——防与矩阵漂移(当前值 = {DRAFT, LOCKED})。
QUOTATION_VOIDABLE: set[str] = {
    s for s, targets in QUOTATION_TRANSITIONS.items() if QuotationStatus.VOID in targets
}


class QuotationOrder(Base, TimestampUpdateMixin):
    __tablename__ = "quotation_orders"
    __table_args__ = (
        # 币种存 ISO4217 三字母大写 code(USD/CNY…),不存中文/自由串;DB 锁死格式,展示走 i18n。
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_qorders_currency_iso4217"),
        # 状态 DB 兜底,bound 到状态机全集(单一源头 QuotationStatus.ALL)。
        CheckConstraint("status IN ('DRAFT','LOCKED','CONVERTED','VOID')", name="ck_qorders_status"),
        # 表头总额反范式落存(行是源、service 维护),DB 兜底非负。
        CheckConstraint("total_amount >= 0", name="ck_qorders_total_amount_nn"),
        # 列表默认 status tab 过滤 + created_at DESC 排序(报价是持续累积单据表)。
        Index("ix_qorders_status_created", "status", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # ON DELETE RESTRICT 显式:客户被报价单引用时不可硬删(同 skus.unit/spu_id 口径)。
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    # 报价人(业务字段):建单默认=created_by,草稿内可重指派;与 created_by(审计归属)不同语义。
    salesperson_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="zh")
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=QuotationStatus.DRAFT)
    # 表头总额 = Σ 行 line_total,service 在保存/改行时维护(单一源头:行是源)。
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # 摘要/主题:一句话标识单据,显示在列表(识别 ≠ 解释,与 remark 不同语义)。
    summary: Mapped[str | None] = mapped_column(String(180), nullable=True)
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
    # 明细备注:逐行注明定制/颜色等(海外报价常用)。
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
