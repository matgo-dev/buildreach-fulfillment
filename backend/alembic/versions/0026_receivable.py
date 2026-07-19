"""0026 应收款:receivables(财务域全局表,独立迁移;镜像 payables 0020)

契约 §1.4。债权在货权转移(发货=出库确认)时成立;粒度 = 每张出库单一张,
与应付(每入库单一张)完全对称。币种/客户取自锚定 SO(单 SO 锚定 ⇒ 单币种天然成立)。
幂等键 = 活动行偏唯一 UNIQUE(outbound_order_id) WHERE voided_at IS NULL:重复确认不生第二张;
撤销出库作废(void)后可重开(作废行退出偏唯一,与新活动行共存)。
balance = GENERATED ALWAYS AS (amount_original - amount_allocated) STORED(镜像 payables)。
status(收款进度)完全派生自 amount_*,不落列。收款单/核销 = 财务步(T15)。

FK 引用列全量索引(owner 硬规则,偏唯一不替代);全部溯源 RESTRICT。

Revision ID: 0026_receivable
Revises: 0025_outbound
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0026_receivable"
down_revision: Union[str, None] = "0025_outbound"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receivables",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("outbound_order_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("amount_original", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_allocated", sa.Numeric(precision=18, scale=2), nullable=False),
        # 生成列:DB 恒等,ORM 只读、不进 INSERT/UPDATE(镜像 payables.balance)。
        sa.Column("balance", sa.Numeric(precision=18, scale=2),
                  sa.Computed("amount_original - amount_allocated", persisted=True)),
        sa.Column("due_at", sa.Date(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 溯源 RESTRICT:出库单 / SO / 客户被应收引用时不可硬删。
        sa.ForeignKeyConstraint(["outbound_order_id"], ["outbound_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_receivables_currency_iso4217"),
        sa.CheckConstraint("amount_original >= 0", name="ck_receivables_amount_original_nn"),
        sa.CheckConstraint(
            "amount_allocated >= 0 AND amount_allocated <= amount_original",
            name="ck_receivables_allocated_range"),
    )
    # FK 引用列全量索引(默认加,不等消费者);与下方活动行偏唯一并存(用途不同)。
    op.create_index(op.f("ix_receivables_outbound_order_id"), "receivables", ["outbound_order_id"])
    op.create_index(op.f("ix_receivables_sales_order_id"), "receivables", ["sales_order_id"])
    op.create_index(op.f("ix_receivables_customer_id"), "receivables", ["customer_id"])
    op.create_index(op.f("ix_receivables_voided_by"), "receivables", ["voided_by"])
    op.create_index(op.f("ix_receivables_created_by"), "receivables", ["created_by"])
    # 活动行过滤路径(镜像 payables.voided_at 索引)。
    op.create_index(op.f("ix_receivables_voided_at"), "receivables", ["voided_at"])
    # 幂等键(仅约束活动行):一张出库单至多一张活动 receivable。
    op.create_index("uq_receivables_outbound_active", "receivables", ["outbound_order_id"],
                    unique=True, postgresql_where=sa.text("voided_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_receivables_outbound_active", table_name="receivables")
    op.drop_index(op.f("ix_receivables_voided_at"), table_name="receivables")
    op.drop_index(op.f("ix_receivables_created_by"), table_name="receivables")
    op.drop_index(op.f("ix_receivables_voided_by"), table_name="receivables")
    op.drop_index(op.f("ix_receivables_customer_id"), table_name="receivables")
    op.drop_index(op.f("ix_receivables_sales_order_id"), table_name="receivables")
    op.drop_index(op.f("ix_receivables_outbound_order_id"), table_name="receivables")
    op.drop_table("receivables")
