"""0043 rename receivable open amount column

Revision ID: 0043_receivable_outstanding
Revises: 0042_payable_amount_outstanding
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0043_receivable_outstanding"
down_revision: Union[str, None] = "0042_payable_amount_outstanding"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_index("ix_receivables_open_aging", table_name="receivables")
    op.alter_column("receivables", "balance", new_column_name="amount_outstanding")
    op.create_index(
        "ix_receivables_open_aging",
        "receivables",
        ["customer_id", "currency", "due_at", "created_at", "id"],
        postgresql_where=sa.text("voided_at IS NULL AND amount_outstanding > 0"),
    )


def downgrade() -> None:
    op.drop_index("ix_receivables_open_aging", table_name="receivables")
    op.alter_column("receivables", "amount_outstanding", new_column_name="balance")
    op.create_index(
        "ix_receivables_open_aging",
        "receivables",
        ["customer_id", "currency", "due_at", "created_at", "id"],
        postgresql_where=sa.text("voided_at IS NULL AND balance > 0"),
    )
