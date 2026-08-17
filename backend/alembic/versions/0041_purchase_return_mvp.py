"""0041 采购退货 MVP:采购退货单 + 供应商贷项单

MVP-A 覆盖「已入库、未出库、供应商接受退回」:
- purchase_return_orders / lines 承载采购侧退货事实;
- ap_credit_memos 承载供应商贷项事实;
- payables 增加 amount_credited,余额生成列改为 original - credited - allocated;
- inventory_movements 增加 PURCHASE_RETURN_ISSUE 来源类型。

Revision ID: 0041_purchase_return_mvp
Revises: 0040_stock_persistence
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0041_purchase_return_mvp"
down_revision: Union[str, None] = "0040_stock_persistence"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "payables",
        sa.Column("amount_credited", sa.Numeric(18, 2), nullable=False,
                  server_default=sa.text("0")),
    )
    op.drop_constraint("ck_payables_allocated_range", "payables", type_="check")
    op.drop_index("ix_payables_open_aging", table_name="payables")
    op.drop_column("payables", "balance")
    op.create_check_constraint(
        "ck_payables_allocated_range",
        "payables",
        "amount_allocated >= 0 AND amount_credited >= 0 "
        "AND amount_allocated + amount_credited <= amount_original",
    )
    op.add_column(
        "payables",
        sa.Column("balance", sa.Numeric(18, 2),
                  sa.Computed("amount_original - amount_credited - amount_allocated",
                              persisted=True)),
    )
    op.alter_column("payables", "amount_credited", server_default=None)
    op.create_index(
        "ix_payables_open_aging",
        "payables",
        ["supplier_id", "currency", "due_at", "created_at", "id"],
        postgresql_where=sa.text("voided_at IS NULL AND balance > 0"),
    )

    op.drop_constraint("ck_inventory_movements_type", "inventory_movements", type_="check")
    op.drop_constraint("ck_inventory_movements_source_type", "inventory_movements", type_="check")
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

    op.create_table(
        "purchase_return_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("inbound_order_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by", sa.Integer(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("returned_by", sa.Integer(), nullable=True),
        sa.Column("return_shipment_reference", sa.String(length=80), nullable=True),
        sa.Column("return_note", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inbound_order_id"], ["inbound_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["returned_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('PENDING_APPROVAL','APPROVED','REJECTED','RETURNED','VOIDED')",
            name="ck_preturns_status"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_preturns_currency_iso4217"),
        sa.CheckConstraint("total_amount >= 0", name="ck_preturns_total_amount_nn"),
    )
    op.create_index(op.f("ix_purchase_return_orders_no"),
                    "purchase_return_orders", ["no"], unique=True)
    op.create_index(op.f("ix_purchase_return_orders_inbound_order_id"),
                    "purchase_return_orders", ["inbound_order_id"])
    op.create_index(op.f("ix_purchase_return_orders_purchase_order_id"),
                    "purchase_return_orders", ["purchase_order_id"])
    op.create_index(op.f("ix_purchase_return_orders_sales_order_id"),
                    "purchase_return_orders", ["sales_order_id"])
    op.create_index(op.f("ix_purchase_return_orders_supplier_id"),
                    "purchase_return_orders", ["supplier_id"])
    op.create_index(op.f("ix_purchase_return_orders_created_by"),
                    "purchase_return_orders", ["created_by"])
    op.create_index(op.f("ix_purchase_return_orders_approved_by"),
                    "purchase_return_orders", ["approved_by"])
    op.create_index(op.f("ix_purchase_return_orders_rejected_by"),
                    "purchase_return_orders", ["rejected_by"])
    op.create_index(op.f("ix_purchase_return_orders_returned_by"),
                    "purchase_return_orders", ["returned_by"])
    op.create_index("ix_preturns_status_created", "purchase_return_orders",
                    ["status", sa.text("created_at DESC")])
    op.create_index("ix_preturns_inbound_created", "purchase_return_orders",
                    ["inbound_order_id", sa.text("created_at DESC")])
    op.create_index("ix_preturns_purchase_created", "purchase_return_orders",
                    ["purchase_order_id", sa.text("created_at DESC")])
    op.create_index("ix_preturns_supplier_created", "purchase_return_orders",
                    ["supplier_id", sa.text("created_at DESC")])

    op.create_table(
        "purchase_return_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("purchase_return_order_id", sa.Integer(), nullable=False),
        sa.Column("inbound_order_line_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column("spec_text_snapshot", sa.Text(), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("line_total", sa.Numeric(18, 2), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["inbound_order_line_id"], ["inbound_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_line_id"], ["purchase_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_return_order_id"], ["purchase_return_orders.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("purchase_return_order_id", "inbound_order_line_id",
                            name="uq_preturn_lines_order_inbound_line"),
        sa.CheckConstraint("qty > 0", name="ck_preturn_lines_qty_pos"),
        sa.CheckConstraint("unit_price >= 0", name="ck_preturn_lines_unit_price_nn"),
        sa.CheckConstraint("line_total >= 0", name="ck_preturn_lines_total_nn"),
        sa.CheckConstraint("sort_order >= 0", name="ck_preturn_lines_sort_nn"),
    )
    op.create_index(op.f("ix_purchase_return_lines_purchase_return_order_id"),
                    "purchase_return_lines", ["purchase_return_order_id"])
    op.create_index(op.f("ix_purchase_return_lines_inbound_order_line_id"),
                    "purchase_return_lines", ["inbound_order_line_id"])
    op.create_index(op.f("ix_purchase_return_lines_purchase_order_line_id"),
                    "purchase_return_lines", ["purchase_order_line_id"])
    op.create_index(op.f("ix_purchase_return_lines_sku_id"),
                    "purchase_return_lines", ["sku_id"])
    op.create_index("ix_preturn_lines_inbound_line_created", "purchase_return_lines",
                    ["inbound_order_line_id", sa.text("created_at DESC")])

    op.create_table(
        "ap_credit_memos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("payable_id", sa.Integer(), nullable=False),
        sa.Column("purchase_return_order_id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("memo_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("posted_by", sa.Integer(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_by", sa.Integer(), nullable=True),
        sa.Column("reject_reason", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["rejected_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["voided_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("memo_type IN ('PURCHASE_RETURN')",
                           name="ck_ap_credit_memos_type"),
        sa.CheckConstraint("status IN ('PENDING_APPROVAL','POSTED','REJECTED','VOIDED')",
                           name="ck_ap_credit_memos_status"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'",
                           name="ck_ap_credit_memos_currency_iso4217"),
        sa.CheckConstraint("amount > 0", name="ck_ap_credit_memos_amount_pos"),
    )
    op.create_index(op.f("ix_ap_credit_memos_no"),
                    "ap_credit_memos", ["no"], unique=True)
    op.create_index(op.f("ix_ap_credit_memos_payable_id"),
                    "ap_credit_memos", ["payable_id"])
    op.create_index(op.f("ix_ap_credit_memos_purchase_return_order_id"),
                    "ap_credit_memos", ["purchase_return_order_id"])
    op.create_index(op.f("ix_ap_credit_memos_supplier_id"),
                    "ap_credit_memos", ["supplier_id"])
    op.create_index(op.f("ix_ap_credit_memos_created_by"),
                    "ap_credit_memos", ["created_by"])
    op.create_index(op.f("ix_ap_credit_memos_posted_at"),
                    "ap_credit_memos", ["posted_at"])
    op.create_index(op.f("ix_ap_credit_memos_posted_by"),
                    "ap_credit_memos", ["posted_by"])
    op.create_index(op.f("ix_ap_credit_memos_rejected_by"),
                    "ap_credit_memos", ["rejected_by"])
    op.create_index(op.f("ix_ap_credit_memos_voided_at"),
                    "ap_credit_memos", ["voided_at"])
    op.create_index(op.f("ix_ap_credit_memos_voided_by"),
                    "ap_credit_memos", ["voided_by"])
    op.create_index("uq_ap_credit_memos_preturn_active", "ap_credit_memos",
                    ["purchase_return_order_id"], unique=True,
                    postgresql_where=sa.text("status != 'VOIDED'"))
    op.create_index("ix_ap_credit_memos_status_created", "ap_credit_memos",
                    ["status", sa.text("created_at DESC")])
    op.create_index("ix_ap_credit_memos_payable_created", "ap_credit_memos",
                    ["payable_id", sa.text("created_at DESC")])
    op.create_index("ix_ap_credit_memos_supplier_created", "ap_credit_memos",
                    ["supplier_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_ap_credit_memos_supplier_created", table_name="ap_credit_memos")
    op.drop_index("ix_ap_credit_memos_payable_created", table_name="ap_credit_memos")
    op.drop_index("ix_ap_credit_memos_status_created", table_name="ap_credit_memos")
    op.drop_index("uq_ap_credit_memos_preturn_active", table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_voided_by"), table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_voided_at"), table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_rejected_by"), table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_posted_by"), table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_posted_at"), table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_created_by"), table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_supplier_id"), table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_purchase_return_order_id"),
                  table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_payable_id"), table_name="ap_credit_memos")
    op.drop_index(op.f("ix_ap_credit_memos_no"), table_name="ap_credit_memos")
    op.drop_table("ap_credit_memos")

    op.drop_index("ix_preturn_lines_inbound_line_created", table_name="purchase_return_lines")
    op.drop_index(op.f("ix_purchase_return_lines_sku_id"), table_name="purchase_return_lines")
    op.drop_index(op.f("ix_purchase_return_lines_purchase_order_line_id"),
                  table_name="purchase_return_lines")
    op.drop_index(op.f("ix_purchase_return_lines_inbound_order_line_id"),
                  table_name="purchase_return_lines")
    op.drop_index(op.f("ix_purchase_return_lines_purchase_return_order_id"),
                  table_name="purchase_return_lines")
    op.drop_table("purchase_return_lines")

    op.drop_index("ix_preturns_supplier_created", table_name="purchase_return_orders")
    op.drop_index("ix_preturns_purchase_created", table_name="purchase_return_orders")
    op.drop_index("ix_preturns_inbound_created", table_name="purchase_return_orders")
    op.drop_index("ix_preturns_status_created", table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_returned_by"),
                  table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_rejected_by"),
                  table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_approved_by"),
                  table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_created_by"),
                  table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_supplier_id"),
                  table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_sales_order_id"),
                  table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_purchase_order_id"),
                  table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_inbound_order_id"),
                  table_name="purchase_return_orders")
    op.drop_index(op.f("ix_purchase_return_orders_no"), table_name="purchase_return_orders")
    op.drop_table("purchase_return_orders")

    op.drop_constraint("ck_inventory_movements_source_type", "inventory_movements", type_="check")
    op.drop_constraint("ck_inventory_movements_type", "inventory_movements", type_="check")
    op.create_check_constraint(
        "ck_inventory_movements_source_type",
        "inventory_movements",
        "source_type IN ('INBOUND_ORDER','OUTBOUND_ORDER')",
    )
    op.create_check_constraint(
        "ck_inventory_movements_type",
        "inventory_movements",
        "movement_type IN ('INBOUND_RECEIVE','INBOUND_UNRECEIVE','OUTBOUND_ISSUE')",
    )

    op.drop_index("ix_payables_open_aging", table_name="payables")
    op.drop_column("payables", "balance")
    op.drop_constraint("ck_payables_allocated_range", "payables", type_="check")
    op.create_check_constraint(
        "ck_payables_allocated_range",
        "payables",
        "amount_allocated >= 0 AND amount_allocated <= amount_original",
    )
    op.add_column(
        "payables",
        sa.Column("balance", sa.Numeric(18, 2),
                  sa.Computed("amount_original - amount_allocated", persisted=True)),
    )
    op.create_index(
        "ix_payables_open_aging",
        "payables",
        ["supplier_id", "currency", "due_at", "created_at", "id"],
        postgresql_where=sa.text("voided_at IS NULL AND balance > 0"),
    )
    op.drop_column("payables", "amount_credited")
