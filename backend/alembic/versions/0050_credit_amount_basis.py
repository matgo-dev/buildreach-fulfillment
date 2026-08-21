"""0050 customer credit amount basis

Revision ID: 0050_credit_amount_basis
Revises: 0049_customer_credit_reverse_idp
Create Date: 2026-08-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0050_credit_amount_basis"
down_revision = "0049_customer_credit_reverse_idp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customer_credit_memos",
        sa.Column(
            "amount_basis",
            sa.Text(),
            nullable=False,
            server_default="历史客户余额贷项人民币金额依据",
        ),
    )
    op.alter_column("customer_credit_memos", "amount_basis", server_default=None)


def downgrade() -> None:
    op.drop_column("customer_credit_memos", "amount_basis")
