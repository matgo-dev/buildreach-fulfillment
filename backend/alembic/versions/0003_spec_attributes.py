"""category_spec_attributes: 分类规格属性模板(一属性一行,正规化)

Revision ID: ec33b7b4504f
Revises: 518529eacb3e

商品目录规格模板表。一属性一行 + DB 层 UNIQUE(category_code,key) 硬保证唯一性 +
4 个 CHECK(value_type / source / sort_order / options⇔enum)。

运营新增属性的稳定 key 由应用层生成独立随机 token(a_<8位 base62>,见
spec_template_service.create_new_attribute):插入前生成、一次 INSERT、不派生自 id,
唯一性靠本表 UNIQUE 兜底。种子模板数据由 app 层 seed(seed_spec_templates)单一源头
负责,不在迁移内写死。

audit 列沿用 TimestampUpdateMixin(不加 created_by):主数据操作者追溯走 audit_log,
对齐全仓口径(唯 quotation 交易域带 created_by)。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ec33b7b4504f"
down_revision = "518529eacb3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "category_spec_attributes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_code", sa.String(length=50), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False, server_default="string"),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["category_code"], ["categories.code"], ondelete="RESTRICT"),
        sa.UniqueConstraint("category_code", "key", name="uq_cat_spec_attr_cat_key"),
        sa.CheckConstraint(
            "value_type IN ('string','number','enum')", name="ck_cat_spec_attr_value_type"),
        sa.CheckConstraint("source IN ('seed','operator')", name="ck_cat_spec_attr_source"),
        sa.CheckConstraint("sort_order >= 0", name="ck_cat_spec_attr_sort_nn"),
        sa.CheckConstraint(
            "(value_type = 'enum') = (options IS NOT NULL)",
            name="ck_cat_spec_attr_options_iff_enum"),
    )


def downgrade() -> None:
    op.drop_table("category_spec_attributes")
