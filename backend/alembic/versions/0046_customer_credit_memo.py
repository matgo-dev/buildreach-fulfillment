"""0046 customer credit memo

Revision ID: 0046_customer_credit_memo
Revises: 0045_inventory_disposition
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0046_customer_credit_memo"
down_revision: Union[str, None] = "0045_inventory_disposition"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "customer_credit_memos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("inventory_disposition_order_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("memo_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("amount_allocated", sa.Numeric(18, 2), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("amount_unallocated", sa.Numeric(18, 2),
                  sa.Computed("amount - amount_allocated", persisted=True)),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("posted_by", sa.Integer(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by", sa.Integer(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_disposition_order_id"],
                                ["inventory_disposition_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("memo_type IN ('INVENTORY_DISPOSITION')",
                           name="ck_customer_credit_memos_type"),
        sa.CheckConstraint("status IN ('PENDING_APPROVAL','POSTED','REJECTED','VOIDED')",
                           name="ck_customer_credit_memos_status"),
        sa.CheckConstraint("currency = 'CNY'",
                           name="ck_customer_credit_memos_currency_cny"),
        sa.CheckConstraint("amount > 0", name="ck_customer_credit_memos_amount_pos"),
        sa.CheckConstraint(
            "amount_allocated >= 0 AND amount_allocated <= amount",
            name="ck_customer_credit_memos_allocated_range"),
        sa.CheckConstraint(
            "(status = 'POSTED') = (posted_at IS NOT NULL AND posted_by IS NOT NULL)",
            name="ck_customer_credit_memos_post_trace"),
        sa.CheckConstraint(
            "(status = 'REJECTED') = (rejected_at IS NOT NULL AND rejected_by IS NOT NULL)",
            name="ck_customer_credit_memos_reject_trace"),
        sa.CheckConstraint(
            "(status = 'VOIDED') = (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
            name="ck_customer_credit_memos_void_trace"),
    )
    op.alter_column("customer_credit_memos", "amount_allocated", server_default=None)
    op.create_index(op.f("ix_customer_credit_memos_no"),
                    "customer_credit_memos", ["no"], unique=True)
    op.create_index(op.f("ix_customer_credit_memos_inventory_disposition_order_id"),
                    "customer_credit_memos", ["inventory_disposition_order_id"])
    op.create_index(op.f("ix_customer_credit_memos_sales_order_id"),
                    "customer_credit_memos", ["sales_order_id"])
    op.create_index(op.f("ix_customer_credit_memos_customer_id"),
                    "customer_credit_memos", ["customer_id"])
    op.create_index(op.f("ix_customer_credit_memos_posted_at"),
                    "customer_credit_memos", ["posted_at"])
    op.create_index(op.f("ix_customer_credit_memos_posted_by"),
                    "customer_credit_memos", ["posted_by"])
    op.create_index(op.f("ix_customer_credit_memos_rejected_by"),
                    "customer_credit_memos", ["rejected_by"])
    op.create_index(op.f("ix_customer_credit_memos_voided_at"),
                    "customer_credit_memos", ["voided_at"])
    op.create_index(op.f("ix_customer_credit_memos_voided_by"),
                    "customer_credit_memos", ["voided_by"])
    op.create_index(op.f("ix_customer_credit_memos_created_by"),
                    "customer_credit_memos", ["created_by"])
    op.create_index(
        "uq_customer_credit_memos_idp_active",
        "customer_credit_memos",
        ["inventory_disposition_order_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING_APPROVAL','POSTED')"),
    )
    op.create_index("ix_customer_credit_memos_status_created",
                    "customer_credit_memos", ["status", sa.text("created_at DESC")])
    op.create_index("ix_customer_credit_memos_customer_created",
                    "customer_credit_memos", ["customer_id", sa.text("created_at DESC")])
    op.create_index("ix_customer_credit_memos_sales_created",
                    "customer_credit_memos", ["sales_order_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_customer_credit_memos_sales_created",
                  table_name="customer_credit_memos")
    op.drop_index("ix_customer_credit_memos_customer_created",
                  table_name="customer_credit_memos")
    op.drop_index("ix_customer_credit_memos_status_created",
                  table_name="customer_credit_memos")
    op.drop_index("uq_customer_credit_memos_idp_active",
                  table_name="customer_credit_memos")
    op.drop_table("customer_credit_memos")
