"""0044 distinguish purchase return order kinds

Revision ID: 0044_purchase_return_kind
Revises: 0043_receivable_outstanding
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0044_purchase_return_kind"
down_revision: Union[str, None] = "0043_receivable_outstanding"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_index("uq_ap_credit_memos_preturn_active", table_name="ap_credit_memos")
    op.create_index(
        "uq_ap_credit_memos_preturn_active",
        "ap_credit_memos",
        ["purchase_return_order_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING_APPROVAL','POSTED')"),
    )
    op.add_column(
        "purchase_return_orders",
        sa.Column(
            "return_kind",
            sa.String(length=40),
            nullable=False,
            server_default="PURCHASE_RETURN",
        ),
    )
    op.alter_column("purchase_return_orders", "return_kind", server_default=None)
    op.create_check_constraint(
        "ck_preturns_kind",
        "purchase_return_orders",
        "return_kind IN ('PURCHASE_RETURN','IN_TRANSIT_CANCELLATION')",
    )
    op.create_index(
        "ix_preturns_kind_status_created",
        "purchase_return_orders",
        ["return_kind", "status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_preturns_kind_status_created", table_name="purchase_return_orders")
    op.drop_constraint("ck_preturns_kind", "purchase_return_orders", type_="check")
    op.drop_column("purchase_return_orders", "return_kind")
    op.drop_index("uq_ap_credit_memos_preturn_active", table_name="ap_credit_memos")
    op.create_index(
        "uq_ap_credit_memos_preturn_active",
        "ap_credit_memos",
        ["purchase_return_order_id"],
        unique=True,
        postgresql_where=sa.text("status != 'VOIDED'"),
    )
