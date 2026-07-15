"""0017 采购:suppliers(供应商主数据)

主流程第3步「按单采购」的主数据表,独立迁移(遵「全局/主数据表不生在功能迁移里」)。
照 customers 档次:code(V{seq:06d})+ 单 name + 联系三件套 + address + status;
加 default_currency(采购默认币种,常≠销售)。补 toggle 端点(customers 缺,建 PO 需选 ACTIVE)。

Revision ID: 0017_supplier
Revises: 0016_sales_order
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_supplier"
down_revision: Union[str, None] = "0016_sales_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("default_currency", sa.String(length=3), nullable=True),
        sa.Column("contact_name", sa.String(length=100), nullable=True),
        sa.Column("contact_phone", sa.String(length=30), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_suppliers_status"),
        sa.CheckConstraint(
            "default_currency IS NULL OR default_currency ~ '^[A-Z]{3}$'",
            name="ck_suppliers_currency_iso4217"),
    )
    op.create_index(op.f("ix_suppliers_code"), "suppliers", ["code"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_suppliers_code"), table_name="suppliers")
    op.drop_table("suppliers")
