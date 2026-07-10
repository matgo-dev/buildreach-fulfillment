"""m1 catalog completion: spu_code + soft delete

Revision ID: 0008_m1_catalog_completion
Revises: 4aee6cdbe0b6
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_m1_catalog_completion"
down_revision = "4aee6cdbe0b6"  # 0007_m1_quotations 的实际 revision id
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. deleted_at(SPU/SKU)
    op.add_column("spus", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("skus", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # 2. spu_code:先 nullable 建列 → 回填 → 置 not null + unique index
    op.add_column("spus", sa.Column("spu_code", sa.String(length=30), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM spus ORDER BY id")).fetchall()
    for i, (spu_id,) in enumerate(rows, start=1):
        conn.execute(
            sa.text("UPDATE spus SET spu_code = :code WHERE id = :id"),
            {"code": f"SPU{i:08d}", "id": spu_id},
        )
    # 对齐编号服务号段,避免后续 allocate 与回填冲突
    # next_seq 语义:已发出的最大序号(allocate() 先 +1 再返回)。
    # 回填后已用到 SPU{len(rows):08d},故 seed = len(rows),而非 len(rows)+1。
    if rows:
        conn.execute(sa.text(
            "INSERT INTO number_sequences (scope, period, next_seq) VALUES ('SPU', '', :n) "
            "ON CONFLICT (scope, period) DO UPDATE SET next_seq = EXCLUDED.next_seq"
        ), {"n": len(rows)})

    op.alter_column("spus", "spu_code", nullable=False)
    op.create_index("ix_spus_spu_code", "spus", ["spu_code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_spus_spu_code", table_name="spus")
    op.drop_column("spus", "spu_code")
    op.drop_column("skus", "deleted_at")
    op.drop_column("spus", "deleted_at")
