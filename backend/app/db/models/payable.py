from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    Date,
    DateTime,
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


class PayableStatus:
    """付款进度(派生值,不落列——完全由 amount_* 决定,落列即双源头)。schema 层输出。"""
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    ALL = (UNPAID, PARTIALLY_PAID, PAID)


def derive_payable_status(amount_original, amount_allocated) -> str:
    """单一派生口径:allocated=0→未付;=original→已付清;之间→部分付。"""
    from decimal import Decimal
    orig = Decimal(str(amount_original))
    alloc = Decimal(str(amount_allocated))
    if alloc <= 0:
        return PayableStatus.UNPAID
    if alloc >= orig:
        return PayableStatus.PAID
    return PayableStatus.PARTIALLY_PAID


class Payable(Base, TimestampUpdateMixin):
    """应付款账层(财务域全局表)。债务在货权转移(收货=入库确认)时成立。

    🔴 整表红线域(供应商 + 成本):端点级 payable:read 门控,不做字段级脱敏。
    粒度 = 每张入库单一张(最贴近发票粒度又不引入发票单据)。幂等键 = 活动行偏唯一。
    status(未付/部分付/已付清)完全派生自 amount_*,不落列(落列即双源头)。
    void 是生命周期轴,与付款状态正交:所有余额/列表/账龄聚合一律 WHERE voided_at IS NULL。
    """
    __tablename__ = "payables"
    __table_args__ = (
        # 币种存 ISO4217 三字母大写 code(复制自 PO,核销要求同币种)。
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payables_currency_iso4217"),
        # 🔴红线:应付原始额非负;创建即定死(P0 无付款/发票,采购单价即应付额)。
        CheckConstraint("amount_original >= 0", name="ck_payables_amount_original_nn"),
        # 已核销 ∈ [0, original](不超付/不负);付款与核销 = 财务步。
        CheckConstraint(
            "amount_allocated >= 0 AND amount_allocated <= amount_original",
            name="ck_payables_allocated_range"),
        # 幂等键(仅约束活动行):一张入库单至多一张活动 payable。撤销入库作废后可重收
        # (作废行 voided_at 非空,退出偏唯一,与新活动行共存)。
        Index("uq_payables_inbound_active", "inbound_order_id", unique=True,
              postgresql_where=text("voided_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 债务来源批次。RESTRICT:被 payable 引用的入库单不可硬删(入库单本就无硬删)。
    inbound_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("inbound_orders.id", ondelete="RESTRICT"), nullable=False)
    # 溯源 + 按 PO 聚合欠款(派生,非唯一)。
    purchase_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("purchase_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    # 债权人;账龄/对账查询路径。
    supplier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # = Σ(行实收 qty × PO 行 unit_price)估算,逐行 quantize 2dp 再求和;P0 创建即定死不可变。
    amount_original: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    # 已核销累计(付款/核销 = 财务步)。
    amount_allocated: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # 恒等式落 DB 最强层(本仓首个 Computed 列):balance = original - allocated,ORM 只读、
    # 不进 INSERT/UPDATE。杜绝三值漂移;财务步列表过滤走此表达式。
    balance: Mapped[float] = mapped_column(
        Numeric(18, 2), Computed("amount_original - amount_allocated", persisted=True))
    # 账期主数据未建,P0 置空;账龄兜底 created_at。
    due_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # void 轴(撤销入库置):非空 = 已作废,行留痕、不进余额与列表聚合。
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # = 确认入库操作人(created_at 即应付成立时刻)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
