"""0050 customer return after outbound

Revision ID: 0050_customer_return
Revises: 0049_customer_credit_reverse_idp
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0050_customer_return"
down_revision: Union[str, None] = "0049_customer_credit_reverse_idp"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_constraint("ck_inventory_movements_type", "inventory_movements", type_="check")
    op.drop_constraint("ck_inventory_movements_source_type", "inventory_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_movements_type",
        "inventory_movements",
        "movement_type IN ("
        "'INBOUND_RECEIVE','INBOUND_UNRECEIVE','OUTBOUND_ISSUE',"
        "'PURCHASE_RETURN_ISSUE','DISPOSITION_HOLD','CUSTOMER_RETURN_RECEIVE')",
    )
    op.create_check_constraint(
        "ck_inventory_movements_source_type",
        "inventory_movements",
        "source_type IN ('INBOUND_ORDER','OUTBOUND_ORDER','PURCHASE_RETURN_ORDER',"
        "'INVENTORY_DISPOSITION_ORDER','CUSTOMER_RETURN_ORDER')",
    )

    op.create_table(
        "customer_return_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("outbound_order_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("received_by", sa.Integer(), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('RECEIVED','VOIDED')", name="ck_customer_returns_status"),
        sa.CheckConstraint(
            "status != 'RECEIVED' OR (received_at IS NOT NULL AND received_by IS NOT NULL)",
            name="ck_customer_returns_receive_trace"),
        sa.CheckConstraint(
            "(status = 'VOIDED') = (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
            name="ck_customer_returns_void_trace"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["outbound_order_id"], ["outbound_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["received_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_customer_return_orders_no"), "customer_return_orders", ["no"], unique=True)
    op.create_index(op.f("ix_customer_return_orders_outbound_order_id"),
                    "customer_return_orders", ["outbound_order_id"])
    op.create_index(op.f("ix_customer_return_orders_sales_order_id"),
                    "customer_return_orders", ["sales_order_id"])
    op.create_index(op.f("ix_customer_return_orders_customer_id"),
                    "customer_return_orders", ["customer_id"])
    op.create_index(op.f("ix_customer_return_orders_received_by"),
                    "customer_return_orders", ["received_by"])
    op.create_index(op.f("ix_customer_return_orders_voided_by"),
                    "customer_return_orders", ["voided_by"])
    op.create_index(op.f("ix_customer_return_orders_voided_at"),
                    "customer_return_orders", ["voided_at"])
    op.create_index(op.f("ix_customer_return_orders_created_by"),
                    "customer_return_orders", ["created_by"])
    op.create_index("ix_customer_returns_outbound_created", "customer_return_orders",
                    ["outbound_order_id", sa.text("created_at DESC")])
    op.create_index("ix_customer_returns_sales_created", "customer_return_orders",
                    ["sales_order_id", sa.text("created_at DESC")])
    op.create_index("ix_customer_returns_customer_created", "customer_return_orders",
                    ["customer_id", sa.text("created_at DESC")])
    op.create_index("ix_customer_returns_status_created", "customer_return_orders",
                    ["status", sa.text("created_at DESC")])

    op.create_table(
        "customer_return_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("customer_return_order_id", sa.Integer(), nullable=False),
        sa.Column("outbound_order_line_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column("spec_text_snapshot", sa.Text(), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("qty > 0", name="ck_customer_return_lines_qty_pos"),
        sa.CheckConstraint("sort_order >= 0", name="ck_customer_return_lines_sort_nn"),
        sa.ForeignKeyConstraint(["customer_return_order_id"],
                                ["customer_return_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outbound_order_line_id"],
                                ["outbound_order_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_line_id"],
                                ["sales_order_lines.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_return_order_id", "outbound_order_line_id",
                            name="uq_customer_return_lines_order_outbound_line"),
    )
    op.create_index(op.f("ix_customer_return_lines_customer_return_order_id"),
                    "customer_return_lines", ["customer_return_order_id"])
    op.create_index(op.f("ix_customer_return_lines_outbound_order_line_id"),
                    "customer_return_lines", ["outbound_order_line_id"])
    op.create_index(op.f("ix_customer_return_lines_sales_order_line_id"),
                    "customer_return_lines", ["sales_order_line_id"])
    op.create_index(op.f("ix_customer_return_lines_sku_id"),
                    "customer_return_lines", ["sku_id"])
    op.create_index("ix_customer_return_lines_outbound_line_created", "customer_return_lines",
                    ["outbound_order_line_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_customer_return_lines_outbound_line_created",
                  table_name="customer_return_lines")
    op.drop_index(op.f("ix_customer_return_lines_sku_id"), table_name="customer_return_lines")
    op.drop_index(op.f("ix_customer_return_lines_sales_order_line_id"),
                  table_name="customer_return_lines")
    op.drop_index(op.f("ix_customer_return_lines_outbound_order_line_id"),
                  table_name="customer_return_lines")
    op.drop_index(op.f("ix_customer_return_lines_customer_return_order_id"),
                  table_name="customer_return_lines")
    op.drop_table("customer_return_lines")

    op.drop_index("ix_customer_returns_status_created", table_name="customer_return_orders")
    op.drop_index("ix_customer_returns_customer_created", table_name="customer_return_orders")
    op.drop_index("ix_customer_returns_sales_created", table_name="customer_return_orders")
    op.drop_index("ix_customer_returns_outbound_created", table_name="customer_return_orders")
    op.drop_index(op.f("ix_customer_return_orders_created_by"), table_name="customer_return_orders")
    op.drop_index(op.f("ix_customer_return_orders_voided_at"), table_name="customer_return_orders")
    op.drop_index(op.f("ix_customer_return_orders_voided_by"), table_name="customer_return_orders")
    op.drop_index(op.f("ix_customer_return_orders_received_by"), table_name="customer_return_orders")
    op.drop_index(op.f("ix_customer_return_orders_customer_id"), table_name="customer_return_orders")
    op.drop_index(op.f("ix_customer_return_orders_sales_order_id"),
                  table_name="customer_return_orders")
    op.drop_index(op.f("ix_customer_return_orders_outbound_order_id"),
                  table_name="customer_return_orders")
    op.drop_index(op.f("ix_customer_return_orders_no"), table_name="customer_return_orders")
    op.drop_table("customer_return_orders")

    op.drop_constraint("ck_inventory_movements_type", "inventory_movements", type_="check")
    op.drop_constraint("ck_inventory_movements_source_type", "inventory_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_movements_type",
        "inventory_movements",
        "movement_type IN ("
        "'INBOUND_RECEIVE','INBOUND_UNRECEIVE','OUTBOUND_ISSUE',"
        "'PURCHASE_RETURN_ISSUE','DISPOSITION_HOLD')",
    )
    op.create_check_constraint(
        "ck_inventory_movements_source_type",
        "inventory_movements",
        "source_type IN ('INBOUND_ORDER','OUTBOUND_ORDER','PURCHASE_RETURN_ORDER',"
        "'INVENTORY_DISPOSITION_ORDER')",
    )
