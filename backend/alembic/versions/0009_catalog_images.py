"""catalog images: spus.main_image/images + skus.image

Revision ID: 0009_catalog_images
Revises: 0008_m1_catalog_completion
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_catalog_images"
down_revision = "0008_m1_catalog_completion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("spus", sa.Column("main_image", sa.String(length=255), nullable=True))
    op.add_column("spus", sa.Column(
        "images", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("skus", sa.Column("image", sa.String(length=255), nullable=True))

    op.execute("UPDATE spus SET main_image = '' WHERE main_image IS NULL")
    op.alter_column("spus", "main_image", nullable=False)


def downgrade() -> None:
    op.drop_column("skus", "image")
    op.drop_column("spus", "images")
    op.drop_column("spus", "main_image")
