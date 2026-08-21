"""0045 inventory disposition

Revision ID: 0045_inventory_disposition
Revises: 0044_purchase_return_kind
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_inventory_disposition"
down_revision: Union[str, None] = "0044_purchase_return_kind"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_constraint("ck_inborders_status", "inbound_orders", type_="check")
    op.create_check_constraint(
        "ck_inborders_status",
        "inbound_orders",
        "status IN ('IN_TRANSIT','RECEIVED','CANCELLED','CLOSED')",
    )

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

    op.drop_constraint("ck_inventory_balances_available_nn", "inventory_balances", type_="check")
    op.drop_column("inventory_balances", "available_qty")
    op.add_column(
        "inventory_balances",
        sa.Column("disposition_qty", sa.Numeric(18, 3), nullable=False,
                  server_default=sa.text("0")),
    )
    op.alter_column("inventory_balances", "disposition_qty", server_default=None)
    op.create_check_constraint(
        "ck_inventory_balances_disposition_nn",
        "inventory_balances",
        "disposition_qty >= 0",
    )
    op.create_check_constraint(
        "ck_inventory_balances_available_nn",
        "inventory_balances",
        "inbound_qty >= outbound_qty + disposition_qty",
    )
    op.add_column(
        "inventory_balances",
        sa.Column(
            "available_qty",
            sa.Numeric(18, 3),
            sa.Computed("inbound_qty - outbound_qty - disposition_qty", persisted=True),
        ),
    )

    op.create_table(
        "inventory_disposition_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("inbound_order_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("payable_id", sa.Integer(), nullable=False),
        sa.Column("purchase_currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("receipt_handling", sa.String(length=30), nullable=False),
        sa.Column("supplier_payable_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("held_at", sa.DateTime(), nullable=True),
        sa.Column("held_by", sa.Integer(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["held_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inbound_order_id"], ["inbound_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payable_id"], ["payables.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('PENDING_RECEIPT','HELD','CLOSED_WITHOUT_RECEIPT','VOIDED')",
                           name="ck_inv_dispositions_status"),
        sa.CheckConstraint(
            "receipt_handling IN ('CLOSE_WITHOUT_RECEIPT','RECEIVE_TO_DISPOSITION')",
            name="ck_inv_dispositions_receipt_handling"),
        sa.CheckConstraint(
            "("
            "receipt_handling = 'CLOSE_WITHOUT_RECEIPT' "
            "AND status IN ('CLOSED_WITHOUT_RECEIPT','VOIDED')"
            ") OR ("
            "receipt_handling = 'RECEIVE_TO_DISPOSITION' "
            "AND status IN ('PENDING_RECEIPT','HELD','VOIDED')"
            ")",
            name="ck_inv_dispositions_status_receipt_handling"),
        sa.CheckConstraint("purchase_currency ~ '^[A-Z]{3}$'",
                           name="ck_inv_dispositions_purchase_currency_iso4217"),
        sa.CheckConstraint("supplier_payable_amount >= 0",
                           name="ck_inv_dispositions_supplier_payable_nn"),
        sa.CheckConstraint(
            "status != 'HELD' OR (held_at IS NOT NULL AND held_by IS NOT NULL)",
            name="ck_inv_dispositions_held_trace_required"),
        sa.CheckConstraint(
            "status NOT IN ('PENDING_RECEIPT','CLOSED_WITHOUT_RECEIPT') "
            "OR (held_at IS NULL AND held_by IS NULL)",
            name="ck_inv_dispositions_preheld_trace_empty"),
        sa.CheckConstraint(
            "(status = 'VOIDED') = (voided_at IS NOT NULL AND voided_by IS NOT NULL)",
            name="ck_inv_dispositions_void_trace"),
    )
    op.create_index(op.f("ix_inventory_disposition_orders_no"),
                    "inventory_disposition_orders", ["no"], unique=True)
    op.create_index(op.f("ix_inventory_disposition_orders_inbound_order_id"),
                    "inventory_disposition_orders", ["inbound_order_id"])
    op.create_index(op.f("ix_inventory_disposition_orders_purchase_order_id"),
                    "inventory_disposition_orders", ["purchase_order_id"])
    op.create_index(op.f("ix_inventory_disposition_orders_sales_order_id"),
                    "inventory_disposition_orders", ["sales_order_id"])
    op.create_index(op.f("ix_inventory_disposition_orders_payable_id"),
                    "inventory_disposition_orders", ["payable_id"])
    op.create_index(op.f("ix_inventory_disposition_orders_created_by"),
                    "inventory_disposition_orders", ["created_by"])
    op.create_index(op.f("ix_inventory_disposition_orders_held_by"),
                    "inventory_disposition_orders", ["held_by"])
    op.create_index(op.f("ix_inventory_disposition_orders_voided_at"),
                    "inventory_disposition_orders", ["voided_at"])
    op.create_index(op.f("ix_inventory_disposition_orders_voided_by"),
                    "inventory_disposition_orders", ["voided_by"])
    op.create_index(
        "uq_inv_dispositions_inbound_active",
        "inventory_disposition_orders",
        ["inbound_order_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'VOIDED'"),
    )
    op.create_index("ix_inv_dispositions_status_created", "inventory_disposition_orders",
                    ["status", sa.text("created_at DESC")])
    op.create_index("ix_inv_dispositions_sales_created", "inventory_disposition_orders",
                    ["sales_order_id", sa.text("created_at DESC")])

    op.create_table(
        "inventory_disposition_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("inventory_disposition_order_id", sa.Integer(), nullable=False),
        sa.Column("inbound_order_line_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column("spec_text_snapshot", sa.Text(), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("line_cost", sa.Numeric(18, 2), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["inbound_order_line_id"], ["inbound_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inventory_disposition_order_id"],
                                ["inventory_disposition_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["purchase_order_line_id"], ["purchase_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inventory_disposition_order_id", "inbound_order_line_id",
                            name="uq_inv_disposition_lines_order_inbound_line"),
        sa.CheckConstraint("qty > 0", name="ck_inv_disposition_lines_qty_pos"),
        sa.CheckConstraint("unit_cost >= 0", name="ck_inv_disposition_lines_unit_cost_nn"),
        sa.CheckConstraint("line_cost >= 0", name="ck_inv_disposition_lines_cost_nn"),
        sa.CheckConstraint("sort_order >= 0", name="ck_inv_disposition_lines_sort_nn"),
    )
    op.create_index(op.f("ix_inventory_disposition_lines_inventory_disposition_order_id"),
                    "inventory_disposition_lines", ["inventory_disposition_order_id"])
    op.create_index(op.f("ix_inventory_disposition_lines_inbound_order_line_id"),
                    "inventory_disposition_lines", ["inbound_order_line_id"])
    op.create_index(op.f("ix_inventory_disposition_lines_purchase_order_line_id"),
                    "inventory_disposition_lines", ["purchase_order_line_id"])
    op.create_index(op.f("ix_inventory_disposition_lines_sku_id"),
                    "inventory_disposition_lines", ["sku_id"])


def downgrade() -> None:
    op.drop_table("inventory_disposition_lines")
    op.drop_index("ix_inv_dispositions_sales_created",
                  table_name="inventory_disposition_orders")
    op.drop_index("ix_inv_dispositions_status_created",
                  table_name="inventory_disposition_orders")
    op.drop_index("uq_inv_dispositions_inbound_active",
                  table_name="inventory_disposition_orders")
    op.drop_table("inventory_disposition_orders")

    op.drop_constraint("ck_inventory_balances_available_nn", "inventory_balances", type_="check")
    op.drop_constraint("ck_inventory_balances_disposition_nn", "inventory_balances", type_="check")
    op.drop_column("inventory_balances", "available_qty")
    op.drop_column("inventory_balances", "disposition_qty")
    op.create_check_constraint(
        "ck_inventory_balances_available_nn",
        "inventory_balances",
        "inbound_qty >= outbound_qty",
    )
    op.add_column(
        "inventory_balances",
        sa.Column("available_qty", sa.Numeric(18, 3),
                  sa.Computed("inbound_qty - outbound_qty", persisted=True)),
    )

    op.drop_constraint("ck_inventory_movements_source_type", "inventory_movements", type_="check")
    op.drop_constraint("ck_inventory_movements_type", "inventory_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_movements_type",
        "inventory_movements",
        "movement_type IN ("
        "'INBOUND_RECEIVE','INBOUND_UNRECEIVE','OUTBOUND_ISSUE',"
        "'PURCHASE_RETURN_ISSUE')",
    )
    op.create_check_constraint(
        "ck_inventory_movements_source_type",
        "inventory_movements",
        "source_type IN ('INBOUND_ORDER','OUTBOUND_ORDER','PURCHASE_RETURN_ORDER')",
    )

    op.drop_constraint("ck_inborders_status", "inbound_orders", type_="check")
    op.create_check_constraint(
        "ck_inborders_status",
        "inbound_orders",
        "status IN ('IN_TRANSIT','RECEIVED','CANCELLED')",
    )
