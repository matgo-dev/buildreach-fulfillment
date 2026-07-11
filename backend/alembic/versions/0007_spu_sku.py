"""spu / sku: 商品目录核心表(SPU + SKU)

Revision ID: 14e188130cf8
Revises: 0006_units

SPU(商品)+ SKU(单品/规格):
- spus: spu_code 唯一、软删 deleted_at、图片列(main_image/images)、category_code
  双索引(等值 btree ix_spus_category_code + 前缀 text_pattern_ops ix_spus_category_code_prefix)。
- skus: 软删 deleted_at、image、unit 为 FK→units.code(ON DELETE RESTRICT,在用单位删不掉)、
  search_text GIN(pg_trgm,扩展在 0002 建)、reference_price 非负 CHECK。

时间戳/软删语义见 app/db/base.py mixin(created_at/updated_at naive UTC;deleted_at tz-aware)。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "14e188130cf8"
down_revision = "0006_units"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "spus",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("spu_code", sa.String(length=30), nullable=False),
        sa.Column("category_code", sa.String(length=50), nullable=False),
        sa.Column("name_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("main_image", sa.String(length=255), nullable=False),
        sa.Column("images", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["category_code"], ["categories.code"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_spus_status"),
    )
    op.create_index("ix_spus_spu_code", "spus", ["spu_code"], unique=True)
    op.create_index(op.f("ix_spus_category_code"), "spus", ["category_code"], unique=False)
    op.create_index(
        "ix_spus_category_code_prefix", "spus", ["category_code"],
        postgresql_ops={"category_code": "text_pattern_ops"},
    )

    op.create_table(
        "skus",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("spu_id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(length=30), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("reference_price", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("spec_jsonb", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("name_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("image", sa.String(length=255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["spu_id"], ["spus.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["unit"], ["units.code"], name="fk_skus_unit_units", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "reference_price IS NULL OR reference_price >= 0", name="ck_skus_ref_price_nn"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_skus_status"),
    )
    op.create_index("ix_skus_search_text_trgm", "skus", ["search_text"], unique=False,
                    postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"})
    op.create_index(op.f("ix_skus_sku_code"), "skus", ["sku_code"], unique=True)
    op.create_index(op.f("ix_skus_spu_id"), "skus", ["spu_id"], unique=False)
    op.create_index("ix_skus_unit", "skus", ["unit"], unique=False)


def downgrade() -> None:
    op.drop_table("skus")
    op.drop_table("spus")
