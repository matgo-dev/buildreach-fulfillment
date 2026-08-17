"""0038 reverse requests: pre-outbound fulfillment cancellation MVP

Revision ID: 0038_reverse_requests
Revises: 0037_schema_rigor_checks_indexes
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038_reverse_requests"
down_revision: Union[str, None] = "0037_schema_rigor_checks_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reverse_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("request_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("inbound_order_id", sa.Integer(), nullable=False),
        sa.Column("goods_status", sa.String(length=20), nullable=False),
        sa.Column("supplier_resolution", sa.String(length=40), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_by", sa.Integer(), nullable=True),
        sa.Column("completion_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("request_type IN ('FULFILLMENT_CANCEL')",
                           name="ck_reverse_requests_type"),
        sa.CheckConstraint("status IN ('PENDING_REVIEW','APPROVED','REJECTED','COMPLETED')",
                           name="ck_reverse_requests_status"),
        sa.CheckConstraint("goods_status IN ('IN_TRANSIT','RECEIVED')",
                           name="ck_reverse_requests_goods_status"),
        sa.CheckConstraint(
            "supplier_resolution IS NULL OR supplier_resolution IN "
            "('SUPPLIER_ACCEPTS_RETURN','COMPANY_BEAR_LOSS')",
            name="ck_reverse_requests_supplier_resolution"),
        sa.CheckConstraint(
            "(status IN ('APPROVED','COMPLETED')) = (supplier_resolution IS NOT NULL)",
            name="ck_reverse_requests_resolution_required"),
        sa.ForeignKeyConstraint(["completed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["inbound_order_id"], ["inbound_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_reverse_requests_no"), "reverse_requests", ["no"], unique=True)
    op.create_index(op.f("ix_reverse_requests_sales_order_id"), "reverse_requests", ["sales_order_id"])
    op.create_index(op.f("ix_reverse_requests_purchase_order_id"), "reverse_requests", ["purchase_order_id"])
    op.create_index(op.f("ix_reverse_requests_inbound_order_id"), "reverse_requests", ["inbound_order_id"])
    op.create_index(op.f("ix_reverse_requests_requested_by"), "reverse_requests", ["requested_by"])
    op.create_index(op.f("ix_reverse_requests_reviewed_by"), "reverse_requests", ["reviewed_by"])
    op.create_index(op.f("ix_reverse_requests_completed_by"), "reverse_requests", ["completed_by"])
    op.create_index("ix_reverse_requests_status_created", "reverse_requests",
                    ["status", sa.text("created_at DESC")])
    op.create_index("ix_reverse_requests_so_created", "reverse_requests",
                    ["sales_order_id", sa.text("created_at DESC")])
    op.create_index("uq_reverse_requests_inbound_active", "reverse_requests", ["inbound_order_id"],
                    unique=True,
                    postgresql_where=sa.text("status IN ('PENDING_REVIEW','APPROVED')"))

    op.create_table(
        "reverse_request_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reverse_request_id", sa.Integer(), nullable=False),
        sa.Column("inbound_order_line_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_line_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("name_snapshot", sa.Text(), nullable=False),
        sa.Column("spec_text_snapshot", sa.Text(), nullable=False),
        sa.Column("unit_snapshot", sa.String(length=20), nullable=False),
        sa.Column("qty", sa.Numeric(18, 3), nullable=False),
        sa.CheckConstraint("qty > 0", name="ck_reverse_request_lines_qty_pos"),
        sa.ForeignKeyConstraint(["inbound_order_line_id"], ["inbound_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_order_line_id"], ["purchase_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reverse_request_id"], ["reverse_requests.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reverse_request_id", "inbound_order_line_id",
                            name="uq_reverse_request_lines_request_inbline"),
    )
    op.create_index(op.f("ix_reverse_request_lines_reverse_request_id"),
                    "reverse_request_lines", ["reverse_request_id"])
    op.create_index(op.f("ix_reverse_request_lines_inbound_order_line_id"),
                    "reverse_request_lines", ["inbound_order_line_id"])
    op.create_index(op.f("ix_reverse_request_lines_purchase_order_line_id"),
                    "reverse_request_lines", ["purchase_order_line_id"])
    op.create_index(op.f("ix_reverse_request_lines_sku_id"), "reverse_request_lines", ["sku_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_reverse_request_lines_sku_id"), table_name="reverse_request_lines")
    op.drop_index(op.f("ix_reverse_request_lines_purchase_order_line_id"),
                  table_name="reverse_request_lines")
    op.drop_index(op.f("ix_reverse_request_lines_inbound_order_line_id"),
                  table_name="reverse_request_lines")
    op.drop_index(op.f("ix_reverse_request_lines_reverse_request_id"),
                  table_name="reverse_request_lines")
    op.drop_table("reverse_request_lines")
    op.drop_index("uq_reverse_requests_inbound_active", table_name="reverse_requests")
    op.drop_index("ix_reverse_requests_so_created", table_name="reverse_requests")
    op.drop_index("ix_reverse_requests_status_created", table_name="reverse_requests")
    op.drop_index(op.f("ix_reverse_requests_completed_by"), table_name="reverse_requests")
    op.drop_index(op.f("ix_reverse_requests_reviewed_by"), table_name="reverse_requests")
    op.drop_index(op.f("ix_reverse_requests_requested_by"), table_name="reverse_requests")
    op.drop_index(op.f("ix_reverse_requests_inbound_order_id"), table_name="reverse_requests")
    op.drop_index(op.f("ix_reverse_requests_purchase_order_id"), table_name="reverse_requests")
    op.drop_index(op.f("ix_reverse_requests_sales_order_id"), table_name="reverse_requests")
    op.drop_index(op.f("ix_reverse_requests_no"), table_name="reverse_requests")
    op.drop_table("reverse_requests")
