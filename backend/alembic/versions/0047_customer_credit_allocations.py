"""0047 customer credit allocations

Revision ID: 0047_customer_credit_allocations
Revises: 0046_customer_credit_memo
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0047_customer_credit_allocations"
down_revision: Union[str, None] = "0046_customer_credit_memo"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_constraint("ck_customer_credit_memos_post_trace",
                       "customer_credit_memos", type_="check")
    op.drop_constraint("ck_customer_credit_memos_reject_trace",
                       "customer_credit_memos", type_="check")
    op.drop_constraint("ck_customer_credit_memos_void_trace",
                       "customer_credit_memos", type_="check")
    op.add_column(
        "customer_credit_memos",
        sa.Column("resubmitted_from_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_ccm_resubmitted_from",
        "customer_credit_memos", "customer_credit_memos",
        ["resubmitted_from_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_index("ix_customer_credit_memos_resubmitted_from",
                    "customer_credit_memos", ["resubmitted_from_id"])
    op.create_check_constraint(
        "ck_customer_credit_memos_post_pair",
        "customer_credit_memos",
        "(posted_at IS NULL) = (posted_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_customer_credit_memos_reject_pair",
        "customer_credit_memos",
        "(rejected_at IS NULL) = (rejected_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_customer_credit_memos_void_pair",
        "customer_credit_memos",
        "(voided_at IS NULL) = (voided_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_customer_credit_memos_post_required",
        "customer_credit_memos",
        "status != 'POSTED' OR (posted_at IS NOT NULL AND posted_by IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_customer_credit_memos_reject_required",
        "customer_credit_memos",
        "status != 'REJECTED' OR (rejected_at IS NOT NULL AND rejected_by IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_customer_credit_memos_void_required",
        "customer_credit_memos",
        "status != 'VOIDED' OR (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
    )

    op.create_table(
        "customer_credit_allocations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_credit_memo_id", sa.Integer(), nullable=False),
        sa.Column("receivable_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("alloc_type", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("reversed_at", sa.DateTime(), nullable=True),
        sa.Column("reversed_by", sa.Integer(), nullable=True),
        sa.Column("reverse_reason", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_credit_memo_id"],
                                ["customer_credit_memos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["receivable_id"], ["receivables.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reversed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount > 0", name="ck_customer_credit_alloc_amount_pos"),
        sa.CheckConstraint("alloc_type IN ('AUTO','MANUAL')",
                           name="ck_customer_credit_alloc_type"),
        sa.CheckConstraint("(reversed_at IS NULL) = (reversed_by IS NULL)",
                           name="ck_customer_credit_alloc_reverse_pair"),
    )
    op.create_index(op.f("ix_customer_credit_allocations_customer_credit_memo_id"),
                    "customer_credit_allocations", ["customer_credit_memo_id"])
    op.create_index(op.f("ix_customer_credit_allocations_receivable_id"),
                    "customer_credit_allocations", ["receivable_id"])
    op.create_index(op.f("ix_customer_credit_allocations_reversed_by"),
                    "customer_credit_allocations", ["reversed_by"])
    op.create_index(op.f("ix_customer_credit_allocations_created_by"),
                    "customer_credit_allocations", ["created_by"])
    op.create_index(
        "uq_customer_credit_alloc_active",
        "customer_credit_allocations",
        ["customer_credit_memo_id", "receivable_id"],
        unique=True,
        postgresql_where=sa.text("reversed_at IS NULL"),
    )
    op.create_index("uq_customer_credit_alloc_idempotency",
                    "customer_credit_allocations", ["idempotency_key"], unique=True)
    op.create_index("ix_customer_credit_alloc_credit_active",
                    "customer_credit_allocations",
                    ["customer_credit_memo_id", "reversed_at"])
    op.create_index("ix_customer_credit_alloc_receivable_active",
                    "customer_credit_allocations",
                    ["receivable_id", "reversed_at"])


def downgrade() -> None:
    op.drop_index("ix_customer_credit_alloc_receivable_active",
                  table_name="customer_credit_allocations")
    op.drop_index("ix_customer_credit_alloc_credit_active",
                  table_name="customer_credit_allocations")
    op.drop_index("uq_customer_credit_alloc_idempotency",
                  table_name="customer_credit_allocations")
    op.drop_index("uq_customer_credit_alloc_active",
                  table_name="customer_credit_allocations")
    op.drop_table("customer_credit_allocations")

    op.drop_constraint("ck_customer_credit_memos_void_required",
                       "customer_credit_memos", type_="check")
    op.drop_constraint("ck_customer_credit_memos_reject_required",
                       "customer_credit_memos", type_="check")
    op.drop_constraint("ck_customer_credit_memos_post_required",
                       "customer_credit_memos", type_="check")
    op.drop_constraint("ck_customer_credit_memos_void_pair",
                       "customer_credit_memos", type_="check")
    op.drop_constraint("ck_customer_credit_memos_reject_pair",
                       "customer_credit_memos", type_="check")
    op.drop_constraint("ck_customer_credit_memos_post_pair",
                       "customer_credit_memos", type_="check")
    op.drop_index("ix_customer_credit_memos_resubmitted_from",
                  table_name="customer_credit_memos")
    op.drop_constraint("fk_ccm_resubmitted_from",
                       "customer_credit_memos", type_="foreignkey")
    op.drop_column("customer_credit_memos", "resubmitted_from_id")
    op.create_check_constraint(
        "ck_customer_credit_memos_void_trace",
        "customer_credit_memos",
        "(status = 'VOIDED') = (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_customer_credit_memos_reject_trace",
        "customer_credit_memos",
        "(status = 'REJECTED') = (rejected_at IS NOT NULL AND rejected_by IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_customer_credit_memos_post_trace",
        "customer_credit_memos",
        "(status = 'POSTED') = (posted_at IS NOT NULL AND posted_by IS NOT NULL)",
    )
