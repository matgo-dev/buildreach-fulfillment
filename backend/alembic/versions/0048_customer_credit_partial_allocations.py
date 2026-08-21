"""0048 customer credit partial allocations

Revision ID: 0048_customer_credit_partial
Revises: 0047_customer_credit_allocations
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0048_customer_credit_partial"
down_revision: Union[str, None] = "0047_customer_credit_allocations"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_index("uq_customer_credit_alloc_active",
                  table_name="customer_credit_allocations")


def downgrade() -> None:
    op.create_index(
        "uq_customer_credit_alloc_active",
        "customer_credit_allocations",
        ["customer_credit_memo_id", "receivable_id"],
        unique=True,
        postgresql_where=sa.text("reversed_at IS NULL"),
    )
