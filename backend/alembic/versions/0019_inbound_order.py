"""0019 入库:inbound_orders + inbound_order_lines(ASN 两态 + 撤销纠错口)

主流程第4步。锚定 1 PO(1 PO : N 入库单,分批到货);供应商发货即建(在途),
货到货代仓确认入库。状态机 IN_TRANSIT→{RECEIVED,CANCELLED},RECEIVED→IN_TRANSIT(撤销入库)。
入库单据零成本列(契约 D3:无价格/金额,币种随 PO);头程物流手工填(§8)。
行 purchase_order_line_id 不单列 UNIQUE 但入复合 UNIQUE(inbound_order_id, purchase_order_line_id)
= 单内唯一(跨单允许分批);跨单累计超收由 service 守卫(含在途)。
应付款(payables)独立生于 0020(财务域全局表不生在功能迁移里)。

Revision ID: 0019_inbound_order
Revises: 0018_purchase_order
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_inbound_order"
down_revision: Union[str, None] = "0018_purchase_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("carrier_name", sa.String(length=100), nullable=True),
        sa.Column("tracking_no", sa.String(length=50), nullable=True),
        sa.Column("shipped_at", sa.Date(), nullable=True),
        sa.Column("eta", sa.Date(), nullable=True),
        sa.Column("arrived_at", sa.Date(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 锚定 PO RESTRICT + 不 UNIQUE(1:N 分批);建单人 RESTRICT。
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('IN_TRANSIT','RECEIVED','CANCELLED')",
                           name="ck_inborders_status"),
    )
    op.create_index(op.f("ix_inbound_orders_no"), "inbound_orders", ["no"], unique=True)
    op.create_index(op.f("ix_inbound_orders_purchase_order_id"), "inbound_orders",
                    ["purchase_order_id"])
    op.create_index(op.f("ix_inbound_orders_tracking_no"), "inbound_orders", ["tracking_no"])
    op.create_index("ix_inborders_status_created", "inbound_orders",
                    ["status", sa.text("created_at DESC")])

    op.create_table(
        "inbound_order_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("inbound_order_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column("spec_text_snapshot", sa.Text(), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        # 在途可改数量 → updated_at。
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["inbound_order_id"], ["inbound_orders.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchase_order_line_id"], ["purchase_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # 单内同一 PO 行至多一行;跨单累计超收由 service 守卫(compute_inbounded_qty)。
        sa.UniqueConstraint("inbound_order_id", "purchase_order_line_id",
                            name="uq_inblines_inb_poline"),
        sa.CheckConstraint("qty > 0", name="ck_inblines_qty_pos"),
        sa.CheckConstraint("sort_order >= 0", name="ck_inblines_sort_nn"),
    )
    op.create_index(op.f("ix_inbound_order_lines_inbound_order_id"), "inbound_order_lines",
                    ["inbound_order_id"])
    op.create_index(op.f("ix_inbound_order_lines_purchase_order_line_id"), "inbound_order_lines",
                    ["purchase_order_line_id"])
    op.create_index(op.f("ix_inbound_order_lines_sku_id"), "inbound_order_lines", ["sku_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_inbound_order_lines_sku_id"), table_name="inbound_order_lines")
    op.drop_index(op.f("ix_inbound_order_lines_purchase_order_line_id"),
                  table_name="inbound_order_lines")
    op.drop_index(op.f("ix_inbound_order_lines_inbound_order_id"),
                  table_name="inbound_order_lines")
    op.drop_table("inbound_order_lines")
    op.drop_index("ix_inborders_status_created", table_name="inbound_orders")
    op.drop_index(op.f("ix_inbound_orders_tracking_no"), table_name="inbound_orders")
    op.drop_index(op.f("ix_inbound_orders_purchase_order_id"), table_name="inbound_orders")
    op.drop_index(op.f("ix_inbound_orders_no"), table_name="inbound_orders")
    op.drop_table("inbound_orders")
