"""0045 company assumed cancellation

Revision ID: 0045_company_assumed_cancellation
Revises: 0044_purchase_return_kind
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0045_company_assumed_cancellation"
down_revision: Union[str, None] = "0044_purchase_return_kind"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_constraint("ck_preturns_status", "purchase_return_orders", type_="check")
    op.drop_constraint("ck_preturns_kind", "purchase_return_orders", type_="check")
    op.add_column(
        "purchase_return_orders",
        sa.Column("customer_refund_amount", sa.Numeric(18, 2), nullable=False,
                  server_default=sa.text("0")),
    )
    op.add_column(
        "purchase_return_orders",
        sa.Column("company_loss_amount", sa.Numeric(18, 2), nullable=False,
                  server_default=sa.text("0")),
    )
    op.alter_column("purchase_return_orders", "customer_refund_amount",
                    server_default=None)
    op.alter_column("purchase_return_orders", "company_loss_amount",
                    server_default=None)
    op.create_check_constraint(
        "ck_preturns_status",
        "purchase_return_orders",
        "status IN ('PENDING_APPROVAL','APPROVED','REJECTED','RETURNED','COMPLETED','VOIDED')",
    )
    op.create_check_constraint(
        "ck_preturns_kind",
        "purchase_return_orders",
        "return_kind IN ('PURCHASE_RETURN','IN_TRANSIT_CANCELLATION',"
        "'COMPANY_ASSUMED_CANCELLATION')",
    )
    op.create_check_constraint(
        "ck_preturns_customer_refund_nn",
        "purchase_return_orders",
        "customer_refund_amount >= 0",
    )
    op.create_check_constraint(
        "ck_preturns_company_loss_nn",
        "purchase_return_orders",
        "company_loss_amount >= 0",
    )
    op.create_check_constraint(
        "ck_preturns_company_loss_identity",
        "purchase_return_orders",
        "return_kind != 'COMPANY_ASSUMED_CANCELLATION' "
        "OR company_loss_amount = total_amount + customer_refund_amount",
    )
    op.create_check_constraint(
        "ck_preturns_non_company_amounts_zero",
        "purchase_return_orders",
        "return_kind = 'COMPANY_ASSUMED_CANCELLATION' "
        "OR (customer_refund_amount = 0 AND company_loss_amount = 0)",
    )
    op.drop_index("ix_preturns_kind_status_created", table_name="purchase_return_orders")
    op.create_index(
        "ix_preturns_kind_status_created",
        "purchase_return_orders",
        ["return_kind", "status", sa.text("created_at DESC")],
    )

    op.drop_constraint("ck_inventory_movements_type", "inventory_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_movements_type",
        "inventory_movements",
        "movement_type IN ("
        "'INBOUND_RECEIVE','INBOUND_UNRECEIVE','OUTBOUND_ISSUE',"
        "'PURCHASE_RETURN_ISSUE','COMPANY_DISPOSITION_HOLD')",
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
        "customer_refunds",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("purchase_return_order_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("paid_by", sa.Integer(), nullable=True),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paid_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_return_order_id"], ["purchase_return_orders.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('PENDING_PAYMENT','PAID','VOIDED')",
                           name="ck_customer_refunds_status"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'",
                           name="ck_customer_refunds_currency_iso4217"),
        sa.CheckConstraint("amount > 0", name="ck_customer_refunds_amount_pos"),
    )
    op.create_index(op.f("ix_customer_refunds_no"), "customer_refunds", ["no"], unique=True)
    op.create_index(op.f("ix_customer_refunds_purchase_return_order_id"),
                    "customer_refunds", ["purchase_return_order_id"])
    op.create_index(op.f("ix_customer_refunds_sales_order_id"),
                    "customer_refunds", ["sales_order_id"])
    op.create_index(op.f("ix_customer_refunds_customer_id"),
                    "customer_refunds", ["customer_id"])
    op.create_index(op.f("ix_customer_refunds_paid_at"), "customer_refunds", ["paid_at"])
    op.create_index(op.f("ix_customer_refunds_paid_by"), "customer_refunds", ["paid_by"])
    op.create_index(op.f("ix_customer_refunds_voided_at"), "customer_refunds", ["voided_at"])
    op.create_index(op.f("ix_customer_refunds_voided_by"), "customer_refunds", ["voided_by"])
    op.create_index(op.f("ix_customer_refunds_created_by"), "customer_refunds", ["created_by"])
    op.create_index(
        "uq_customer_refunds_preturn_active",
        "customer_refunds",
        ["purchase_return_order_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'VOIDED'"),
    )
    op.create_index("ix_customer_refunds_customer_created", "customer_refunds",
                    ["customer_id", sa.text("created_at DESC")])
    op.create_index("ix_customer_refunds_status_created", "customer_refunds",
                    ["status", sa.text("created_at DESC")])

    op.create_table(
        "company_loss_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("purchase_return_order_id", sa.Integer(), nullable=False),
        sa.Column("payable_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("supplier_payable_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("customer_refund_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=False),
        sa.Column("posted_by", sa.Integer(), nullable=False),
        sa.Column("voided_at", sa.DateTime(), nullable=True),
        sa.Column("voided_by", sa.Integer(), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["payable_id"], ["payables.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_return_order_id"], ["purchase_return_orders.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('POSTED','VOIDED')", name="ck_company_losses_status"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'",
                           name="ck_company_losses_currency_iso4217"),
        sa.CheckConstraint("amount > 0", name="ck_company_losses_amount_pos"),
        sa.CheckConstraint("supplier_payable_amount >= 0",
                           name="ck_company_losses_supplier_payable_nn"),
        sa.CheckConstraint("customer_refund_amount >= 0",
                           name="ck_company_losses_customer_refund_nn"),
        sa.CheckConstraint("amount = supplier_payable_amount + customer_refund_amount",
                           name="ck_company_losses_amount_identity"),
    )
    op.create_index(op.f("ix_company_loss_entries_no"), "company_loss_entries", ["no"],
                    unique=True)
    op.create_index(op.f("ix_company_loss_entries_purchase_return_order_id"),
                    "company_loss_entries", ["purchase_return_order_id"])
    op.create_index(op.f("ix_company_loss_entries_payable_id"),
                    "company_loss_entries", ["payable_id"])
    op.create_index(op.f("ix_company_loss_entries_sales_order_id"),
                    "company_loss_entries", ["sales_order_id"])
    op.create_index(op.f("ix_company_loss_entries_posted_at"),
                    "company_loss_entries", ["posted_at"])
    op.create_index(op.f("ix_company_loss_entries_posted_by"),
                    "company_loss_entries", ["posted_by"])
    op.create_index(op.f("ix_company_loss_entries_voided_at"),
                    "company_loss_entries", ["voided_at"])
    op.create_index(op.f("ix_company_loss_entries_voided_by"),
                    "company_loss_entries", ["voided_by"])
    op.create_index(op.f("ix_company_loss_entries_created_by"),
                    "company_loss_entries", ["created_by"])
    op.create_index(
        "uq_company_losses_preturn_active",
        "company_loss_entries",
        ["purchase_return_order_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'VOIDED'"),
    )
    op.create_index("ix_company_losses_status_created", "company_loss_entries",
                    ["status", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_company_losses_status_created", table_name="company_loss_entries")
    op.drop_index("uq_company_losses_preturn_active", table_name="company_loss_entries")
    op.drop_table("company_loss_entries")
    op.drop_index("ix_customer_refunds_status_created", table_name="customer_refunds")
    op.drop_index("ix_customer_refunds_customer_created", table_name="customer_refunds")
    op.drop_index("uq_customer_refunds_preturn_active", table_name="customer_refunds")
    op.drop_table("customer_refunds")

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
    op.drop_constraint("ck_inventory_movements_type", "inventory_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_movements_type",
        "inventory_movements",
        "movement_type IN ("
        "'INBOUND_RECEIVE','INBOUND_UNRECEIVE','OUTBOUND_ISSUE',"
        "'PURCHASE_RETURN_ISSUE')",
    )

    op.drop_index("ix_preturns_kind_status_created", table_name="purchase_return_orders")
    op.drop_constraint("ck_preturns_non_company_amounts_zero", "purchase_return_orders",
                       type_="check")
    op.drop_constraint("ck_preturns_company_loss_identity", "purchase_return_orders",
                       type_="check")
    op.drop_constraint("ck_preturns_company_loss_nn", "purchase_return_orders", type_="check")
    op.drop_constraint("ck_preturns_customer_refund_nn", "purchase_return_orders", type_="check")
    op.drop_constraint("ck_preturns_kind", "purchase_return_orders", type_="check")
    op.drop_constraint("ck_preturns_status", "purchase_return_orders", type_="check")
    op.drop_column("purchase_return_orders", "company_loss_amount")
    op.drop_column("purchase_return_orders", "customer_refund_amount")
    op.create_check_constraint(
        "ck_preturns_status",
        "purchase_return_orders",
        "status IN ('PENDING_APPROVAL','APPROVED','REJECTED','RETURNED','VOIDED')",
    )
    op.create_check_constraint(
        "ck_preturns_kind",
        "purchase_return_orders",
        "return_kind IN ('PURCHASE_RETURN','IN_TRANSIT_CANCELLATION')",
    )
    op.create_index(
        "ix_preturns_kind_status_created",
        "purchase_return_orders",
        ["return_kind", "status", sa.text("created_at DESC")],
    )
