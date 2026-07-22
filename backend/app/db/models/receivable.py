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


class ReceivableStatus:
    """收款进度(派生值,不落列——完全由 amount_* 决定,落列即双源头)。schema 层输出。"""
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    ALL = (UNPAID, PARTIALLY_PAID, PAID)


def derive_receivable_status(amount_original, amount_allocated) -> str:
    """单一派生口径(镜像 derive_payable_status):先判收清(allocated>=original,含 0 金额单据——
    余额 0 即无欠款),再判未收;之间→部分收。判序不可倒:先判 alloc<=0 会把 0 金额单
    永远钉在「未收」(SO 行 unit_price 允许 0,此边界必测)。"""
    from decimal import Decimal
    orig = Decimal(str(amount_original))
    alloc = Decimal(str(amount_allocated))
    if alloc >= orig:
        return ReceivableStatus.PAID
    if alloc <= 0:
        return ReceivableStatus.UNPAID
    return ReceivableStatus.PARTIALLY_PAID


class Receivable(Base, TimestampUpdateMixin):
    """应收款账层(财务域全局表)。债权在货权转移(发货=出库确认)时成立,
    与应付(每入库单一张)完全对称。

    🔴 整表红线域(客户售价):端点级 receivable:read 门控,不做字段级脱敏。
    粒度 = 每张出库单一张。幂等键 = 活动行偏唯一。currency/customer 取自锚定 SO
    (单 SO 锚定 ⇒ 单币种天然成立)。status(未收/部分收/已收清)完全派生自 amount_*,不落列。
    void 是生命周期轴,与收款状态正交:所有余额/列表/账龄聚合一律 WHERE voided_at IS NULL。
    """
    __tablename__ = "receivables"
    __table_args__ = (
        # 币种存 ISO4217 三字母大写 code(取自 SO,核销要求同币种)。
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_receivables_currency_iso4217"),
        # 🔴红线:应收原始额非负;确认时定死(= Σ 行 qty × SO 行 unit_price)。
        CheckConstraint("amount_original >= 0", name="ck_receivables_amount_original_nn"),
        # 已核销 ∈ [0, original](不超收/不负);收款与核销 = 财务步(T15)。
        CheckConstraint(
            "amount_allocated >= 0 AND amount_allocated <= amount_original",
            name="ck_receivables_allocated_range"),
        # 幂等键(仅约束活动行):一张出库单至多一张活动 receivable(撤销出库作废后可重建)。
        # 单一源头补漏:此偏唯一原仅生在迁移 0026,未落 model,create_all 的测试库缺此约束
        # (model↔迁移漂移)。镜像 payables uq_payables_inbound_active,收口回 model 层。
        Index("uq_receivables_outbound_active", "outbound_order_id", unique=True,
              postgresql_where=text("voided_at IS NULL")),
        # 账龄 partial composite 索引(财务步 F1):自动核销候选查询(客户+币种+未结清+账龄序)
        # 过滤+锁序一并走索引、排除已结清行,翻 100 倍不退化。谓词含生成列 balance(PG 接受)。
        Index("ix_receivables_open_aging",
              "customer_id", "currency", "due_at", "created_at", "id",
              postgresql_where=text("voided_at IS NULL AND balance > 0")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 债权来源批次。RESTRICT:被 receivable 引用的出库单不可硬删。
    # 全量索引(FK 默认加,不等消费者)+ 活动行偏唯一(幂等键,见迁移 0026)双索引:
    # 前者服务 FK 侧查找与含作废行的溯源,后者只约束活动行。
    outbound_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("outbound_orders.id", ondelete="RESTRICT"),
        nullable=False, index=True)
    # 溯源 + 按 SO 聚合应收(派生,非唯一)。
    sales_order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    # 债务人;核销按客户找单的查询路径。
    customer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    # = Σ(行 qty × SO 行 unit_price),逐行 quantize 2dp(ROUND_HALF_UP)再求和;确认即定死不可变。
    amount_original: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    # 已核销累计(收款/核销 = 财务步)。
    amount_allocated: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    # 恒等式落 DB 最强层(镜像 payables):balance = original - allocated,ORM 只读、
    # 不进 INSERT/UPDATE。杜绝三值漂移;财务步列表过滤走此表达式。
    balance: Mapped[float] = mapped_column(
        Numeric(18, 2), Computed("amount_original - amount_allocated", persisted=True))
    # 账期主数据未建,P0 置空;账龄兜底 created_at(due_at 优先,Date 非 timestamp)。
    due_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # void 轴(撤销出库置):非空 = 已作废,行留痕、不进余额与列表聚合。
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    voided_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # = 确认出库操作人(created_at 即应收成立时刻)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
