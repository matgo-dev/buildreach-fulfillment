"""0020 应付款:payables(财务域全局表,独立迁移)

债务在货权转移(收货=入库确认)时成立;粒度 = 每张入库单一张。
幂等键 = 活动行偏唯一 UNIQUE(inbound_order_id) WHERE voided_at IS NULL:重复确认不生第二张;
撤销入库作废(void)后可重收(作废行退出偏唯一,与新活动行共存)。
balance = GENERATED ALWAYS AS (amount_original - amount_allocated) STORED —— 本仓首个生成列,
恒等式落 DB 最强层杜绝三值漂移。status(付款进度)/ 欠款聚合完全派生,不落列。
账层无业务号(契约 D9)。payments/allocations/receivables = 财务步。

Revision ID: 0020_payable
Revises: 0019_inbound_order
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020_payable"
down_revision: Union[str, None] = "0019_inbound_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payables",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("inbound_order_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("amount_original", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_allocated", sa.Numeric(precision=18, scale=2), nullable=False),
        # 生成列:DB 恒等,ORM 只读、不进 INSERT/UPDATE。
        sa.Column("balance", sa.Numeric(precision=18, scale=2),
                  sa.Computed("amount_original - amount_allocated", persisted=True)),
        sa.Column("due_at", sa.Date(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 溯源 RESTRICT:入库单/PO/供应商被应付引用时不可硬删。
        sa.ForeignKeyConstraint(["inbound_order_id"], ["inbound_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_payables_currency_iso4217"),
        sa.CheckConstraint("amount_original >= 0", name="ck_payables_amount_original_nn"),
        sa.CheckConstraint(
            "amount_allocated >= 0 AND amount_allocated <= amount_original",
            name="ck_payables_allocated_range"),
    )
    op.create_index(op.f("ix_payables_purchase_order_id"), "payables", ["purchase_order_id"])
    op.create_index(op.f("ix_payables_supplier_id"), "payables", ["supplier_id"])
    op.create_index(op.f("ix_payables_voided_at"), "payables", ["voided_at"])
    # 幂等键(仅约束活动行):一张入库单至多一张活动 payable。
    op.create_index("uq_payables_inbound_active", "payables", ["inbound_order_id"],
                    unique=True, postgresql_where=sa.text("voided_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_payables_inbound_active", table_name="payables")
    op.drop_index(op.f("ix_payables_voided_at"), table_name="payables")
    op.drop_index(op.f("ix_payables_supplier_id"), table_name="payables")
    op.drop_index(op.f("ix_payables_purchase_order_id"), table_name="payables")
    op.drop_table("payables")
