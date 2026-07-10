"""spus.category_code 前缀查询索引(text_pattern_ops)

Revision ID: 0011_spu_category_prefix_idx
Revises: 0010_spec_attributes_normalize

Revision id 缩短为 0011_spu_category_prefix_idx(28 字符):alembic_version.
version_num 列是 varchar(32),原拟 id(0011_spus_category_code_prefix_index,
36 字符)会在 alembic upgrade 时因 StringDataRightTruncation 报错——已实测
踩坑,故改用此短 id,索引名本身仍用完整的 ix_spus_category_code_prefix。

品类子树前缀过滤(list_spus 的 category_code 从精确匹配改为
`code == 输入 OR code LIKE 输入||'.%'`)要走索引才不做 seqscan。本库
locale 是 en_US.UTF-8(非 C locale),默认 btree opclass 不支持前缀
LIKE 走索引扫描,需额外建 text_pattern_ops 索引(标准物化路径前缀查询
落地手法,同 Odoo 给 parent_path 单独建索引)。

保留原 ix_spus_category_code(等值查询用),两者分工:等值走原索引,
前缀 LIKE 走本迁移新建的 ix_spus_category_code_prefix。
"""
from __future__ import annotations

from alembic import op

revision = "0011_spu_category_prefix_idx"
down_revision = "0010_spec_attributes_normalize"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_spus_category_code_prefix", "spus", ["category_code"],
        postgresql_ops={"category_code": "text_pattern_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_spus_category_code_prefix", table_name="spus")
