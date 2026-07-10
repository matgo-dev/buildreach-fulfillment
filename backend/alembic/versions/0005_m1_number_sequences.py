"""m1 number sequences（编号服务·通用子域,独立于业务表）

Revision ID: b2f4a1c8d9e0
Revises: 103eb408942b
Create Date: 2026-07-09 22:34:30.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2f4a1c8d9e0'
down_revision: Union[str, None] = '103eb408942b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('number_sequences',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('scope', sa.String(length=30), nullable=False),
    sa.Column('period', sa.String(length=10), nullable=False),
    sa.Column('next_seq', sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scope', 'period', name='uq_number_scope_period')
    )


def downgrade() -> None:
    op.drop_table('number_sequences')
