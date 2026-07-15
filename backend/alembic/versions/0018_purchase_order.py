"""0018 采购:purchase_orders + purchase_order_lines(按单采购)

主流程第3步。基于某张 SO 独立建的新单据(无「转」语义):SKU 范围与数量上限被 SO 约束,
SO 自身状态不改。source_sales_order_id 不 UNIQUE(SO:PO=1:N,按供应商拆单);
行 source_sales_order_line_id 不单列 UNIQUE 但入复合 UNIQUE(purchase_order_id, source_sales_order_line_id)
= PO 内唯一(跨 PO 允许分批/分供应商/取消重下)。跨 PO 累计超采由 service 守卫。
采购价/金额=成本红线,响应对无 read_cost 者置 null。

Revision ID: 0018_purchase_order
Revises: 0017_supplier
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_purchase_order"
down_revision: Union[str, None] = "0017_supplier"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("source_sales_order_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 来源 SO RESTRICT + 不 UNIQUE(1:N);供应商 RESTRICT;建单人 RESTRICT。
        sa.ForeignKeyConstraint(["source_sales_order_id"], ["sales_orders.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('DRAFT','CONFIRMED','CANCELLED')",
                           name="ck_porders_status"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_porders_currency_iso4217"),
        sa.CheckConstraint("total_amount >= 0", name="ck_porders_total_amount_nn"),
    )
    op.create_index(op.f("ix_purchase_orders_no"), "purchase_orders", ["no"], unique=True)
    op.create_index(op.f("ix_purchase_orders_source_sales_order_id"), "purchase_orders",
                    ["source_sales_order_id"])
    op.create_index(op.f("ix_purchase_orders_supplier_id"), "purchase_orders", ["supplier_id"])
    op.create_index("ix_porders_status_created", "purchase_orders",
                    ["status", sa.text("created_at DESC")])

    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("source_sales_order_line_id", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column("spec_text_snapshot", sa.Text(), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=20), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        # PO 草稿行可改数量/价(非 write-once)→ updated_at。
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_sales_order_line_id"], ["sales_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # PO 内同一 SO 行至多一行(挡「一 payload 重复提交同 so_line 合计超采」);
        # 跨 PO 累计超采由 service 守卫(assert_within_so_line_quota)负责。
        sa.UniqueConstraint("purchase_order_id", "source_sales_order_line_id",
                            name="uq_plines_po_soline"),
        sa.CheckConstraint("qty > 0", name="ck_plines_qty_pos"),
        sa.CheckConstraint("unit_price >= 0", name="ck_plines_unit_price_nn"),
        sa.CheckConstraint("line_total >= 0", name="ck_plines_line_total_nn"),
        sa.CheckConstraint("sort_order >= 0", name="ck_plines_sort_nn"),
    )
    op.create_index(op.f("ix_purchase_order_lines_purchase_order_id"), "purchase_order_lines",
                    ["purchase_order_id"])
    op.create_index(op.f("ix_purchase_order_lines_sku_id"), "purchase_order_lines", ["sku_id"])
    op.create_index(op.f("ix_purchase_order_lines_source_sales_order_line_id"),
                    "purchase_order_lines", ["source_sales_order_line_id"])


def downgrade() -> None:
    # 先 lines 的 index → table,再 header(照 0016 销毁顺序)。
    op.drop_index(op.f("ix_purchase_order_lines_source_sales_order_line_id"),
                  table_name="purchase_order_lines")
    op.drop_index(op.f("ix_purchase_order_lines_sku_id"), table_name="purchase_order_lines")
    op.drop_index(op.f("ix_purchase_order_lines_purchase_order_id"),
                  table_name="purchase_order_lines")
    op.drop_table("purchase_order_lines")
    op.drop_index("ix_porders_status_created", table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_supplier_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_source_sales_order_id"), table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_no"), table_name="purchase_orders")
    op.drop_table("purchase_orders")
