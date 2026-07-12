"""units: SKU 售卖单位专表(主数据,code-as-PK)

Revision ID: 0006_units
Revises: b2f4a1c8d9e0

主数据/引用表,独立迁移(不塞进 spu/sku 业务迁移)。code 纯 ASCII 稳定键做 PK
(同 categories.code 契约,小查表、code 永久不变);sku.unit FK 引它(见 0007)。
2 个 CHECK:code 格式自证 + sort_order 非负。不加 created_by:主数据操作者追溯走
audit_log,对齐 category_spec_attributes 口径。

种子单位数据由 app 层 seed(seed_units)单一源头负责,迁移只建空表:部署时 run_all_seeds
填入 units 行,skus 空表不会 FK 违约。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_units"
down_revision = "b2f4a1c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "units",
        sa.Column("code", sa.String(length=20), primary_key=True),
        sa.Column("label_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("code ~ '^[a-z0-9_]+$'", name="ck_units_code_fmt"),
        sa.CheckConstraint("sort_order >= 0", name="ck_units_sort_nn"),
    )


def downgrade() -> None:
    op.drop_table("units")
