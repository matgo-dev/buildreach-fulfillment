"""0016 转销售:sales_orders + sales_order_lines(锁档报价→销售单)

主流程第2步。分离文档 + 下游反向 FK(source_quotation_id → quotation_orders.id,UNIQUE
硬保证一报价≤一销售单);行平移报价行快照 + source_quotation_line_id(UNIQUE 挡行级重复)。
报价侧零改动(CONVERTED 转移由 service 驱动,矩阵已含 LOCKED→CONVERTED)。

Revision ID: 0016_sales_order
Revises: 0015_customer_name_single
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_sales_order"
down_revision: Union[str, None] = "0015_customer_name_single"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("source_quotation_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("salesperson_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("summary", sa.String(length=180), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 来源报价 RESTRICT(销售单在引用,报价不可硬删);UNIQUE = 1:1 不重复转的最强层保证。
        sa.ForeignKeyConstraint(["source_quotation_id"], ["quotation_orders.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["salesperson_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_quotation_id", name="uq_sorders_source_quotation"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_sorders_currency_iso4217"),
        sa.CheckConstraint("status IN ('CONFIRMED')", name="ck_sorders_status"),
        sa.CheckConstraint("total_amount >= 0", name="ck_sorders_total_amount_nn"),
    )
    op.create_index(op.f("ix_sales_orders_no"), "sales_orders", ["no"], unique=True)
    op.create_index(op.f("ix_sales_orders_customer_id"), "sales_orders", ["customer_id"])
    op.create_index(op.f("ix_sales_orders_salesperson_id"), "sales_orders", ["salesperson_id"])
    op.create_index("ix_sorders_status_created", "sales_orders",
                    ["status", sa.text("created_at DESC")])

    op.create_table(
        "sales_order_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("source_quotation_line_id", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column("spec_text_snapshot", sa.Text(), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=20), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        # 冻结快照行 write-once → 仅 created_at(TimestampMixin),无 updated_at。
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_quotation_line_id"], ["quotation_lines.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # 行级 1:1 硬保证:同一报价行不可重复入单(挡复制逻辑 bug)。
        sa.UniqueConstraint("source_quotation_line_id", name="uq_slines_source_quotation_line"),
        sa.CheckConstraint("qty > 0", name="ck_slines_qty_pos"),
        sa.CheckConstraint("unit_price >= 0", name="ck_slines_unit_price_nn"),
        sa.CheckConstraint("line_total >= 0", name="ck_slines_line_total_nn"),
        sa.CheckConstraint("sort_order >= 0", name="ck_slines_sort_nn"),
    )
    op.create_index(op.f("ix_sales_order_lines_sales_order_id"), "sales_order_lines",
                    ["sales_order_id"])
    op.create_index(op.f("ix_sales_order_lines_sku_id"), "sales_order_lines", ["sku_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_sales_order_lines_sku_id"), table_name="sales_order_lines")
    op.drop_index(op.f("ix_sales_order_lines_sales_order_id"), table_name="sales_order_lines")
    op.drop_table("sales_order_lines")
    op.drop_index("ix_sorders_status_created", table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_salesperson_id"), table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_customer_id"), table_name="sales_orders")
    op.drop_index(op.f("ix_sales_orders_no"), table_name="sales_orders")
    op.drop_table("sales_orders")
