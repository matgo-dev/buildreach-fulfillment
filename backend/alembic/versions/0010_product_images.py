"""product_images: 商品图片规范化表(SPU 图 + SKU 图同表);删 spus/skus 旧图列

Revision ID: 0010_product_images
Revises: d9f1a2b3c4e5 (0009_m1_schema_retrofit)

设计:docs/superpowers/specs/2026-07-12-0514-商品图片建模-design.md(过独立 DB 评审)。
- 建 product_images:spu_id/sku_id(均 FK CASCADE)、image_key、image_type(CHECK MAIN/GALLERY/DETAIL)、
  sort_order、created_at/updated_at(naive UTC,同全库口径)。无 created_by(组合子行,归属在父 SPU +
  audit_logs)、无软删(图片是内容,硬删)。
- 部分唯一:每 SPU 至多一 SPU 级封面 MAIN;身份键 UNIQUE(spu_id,image_key) WHERE sku_id IS NULL(+SKU 镜像)。
- 删 spus.main_image / spus.images / skus.image(图片迁到新表)。
- 索引名与模型 __table_args__ 一致(create_all 与 alembic 单一源头)。

dev 无历史数据、按「重建库」约定(dropdb/createdb),不做数据回填;downgrade 对称重建三列。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_product_images"
down_revision = "d9f1a2b3c4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_images",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("spu_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=True),
        sa.Column("image_key", sa.String(length=255), nullable=False),
        sa.Column("image_type", sa.String(length=20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["spu_id"], ["spus.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("image_type IN ('MAIN','GALLERY','DETAIL')",
                           name="ck_product_images_type"),
    )
    op.create_index("uq_product_images_spu_main", "product_images", ["spu_id"], unique=True,
                    postgresql_where=sa.text("image_type = 'MAIN' AND sku_id IS NULL"))
    op.create_index("uq_product_images_spu_key", "product_images", ["spu_id", "image_key"],
                    unique=True, postgresql_where=sa.text("sku_id IS NULL"))
    op.create_index("uq_product_images_sku_key", "product_images", ["sku_id", "image_key"],
                    unique=True, postgresql_where=sa.text("sku_id IS NOT NULL"))
    op.create_index("ix_product_images_spu_type", "product_images", ["spu_id", "image_type"])
    op.create_index("ix_product_images_sku", "product_images", ["sku_id"])

    # 旧反规范化图列迁到 product_images
    op.drop_column("spus", "main_image")
    op.drop_column("spus", "images")
    op.drop_column("skus", "image")


def downgrade() -> None:
    # 对称重建三列(main_image NOT NULL 需 server_default 以在有行时可加)
    op.add_column("skus", sa.Column("image", sa.String(length=255), nullable=True))
    op.add_column("spus", sa.Column(
        "images", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'[]'::jsonb")))
    op.add_column("spus", sa.Column(
        "main_image", sa.String(length=255), nullable=False, server_default=""))
    op.drop_table("product_images")
