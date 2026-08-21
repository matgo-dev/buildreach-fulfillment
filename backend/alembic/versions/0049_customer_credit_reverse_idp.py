"""0049 customer credit reverse idempotency

Revision ID: 0049_customer_credit_reverse_idp
Revises: 0048_customer_credit_partial
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0049_customer_credit_reverse_idp"
down_revision: Union[str, None] = "0048_customer_credit_partial"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "customer_credit_allocations",
        sa.Column("reverse_idempotency_key", sa.String(length=120), nullable=True),
    )
    op.create_index(
        "uq_customer_credit_alloc_reverse_idempotency",
        "customer_credit_allocations",
        ["reverse_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("reverse_idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_customer_credit_alloc_reverse_idempotency",
                  table_name="customer_credit_allocations")
    op.drop_column("customer_credit_allocations", "reverse_idempotency_key")
