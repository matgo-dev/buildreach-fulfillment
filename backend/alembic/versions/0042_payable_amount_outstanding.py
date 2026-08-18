"""0042 rename payable open amount column

Revision ID: 0042_payable_amount_outstanding
Revises: 0041_purchase_return_mvp
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0042_payable_amount_outstanding"
down_revision: Union[str, None] = "0041_purchase_return_mvp"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_index("ix_payables_open_aging", table_name="payables")
    op.alter_column("payables", "balance", new_column_name="amount_outstanding")
    op.create_index(
        "ix_payables_open_aging",
        "payables",
        ["supplier_id", "currency", "due_at", "created_at", "id"],
        postgresql_where=sa.text("voided_at IS NULL AND amount_outstanding > 0"),
    )


def downgrade() -> None:
    op.drop_index("ix_payables_open_aging", table_name="payables")
    op.alter_column("payables", "amount_outstanding", new_column_name="balance")
    op.create_index(
        "ix_payables_open_aging",
        "payables",
        ["supplier_id", "currency", "due_at", "created_at", "id"],
        postgresql_where=sa.text("voided_at IS NULL AND balance > 0"),
    )
