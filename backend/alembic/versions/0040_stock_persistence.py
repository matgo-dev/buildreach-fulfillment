"""0040 库存落库:销售单维度库存流水 + 余额

本迁移不改变库存归属模型:库存仍归属销售单,不引入自由库存/仓库维度。
现有已确认入库和已确认出库回填为 inventory_movements,再聚合生成 inventory_balances。

Revision ID: 0040_stock_persistence
Revises: 0038_outbound_draft_unique
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0040_stock_persistence"
down_revision: Union[str, None] = "0038_outbound_draft_unique"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "inventory_balances",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("inbound_qty", sa.Numeric(18, 3), nullable=False),
        sa.Column("outbound_qty", sa.Numeric(18, 3), nullable=False),
        # 生成列:DB 恒等,ORM 只读、不进 INSERT/UPDATE。杜绝 inbound/outbound/available 三值漂移。
        sa.Column("available_qty", sa.Numeric(18, 3),
                  sa.Computed("inbound_qty - outbound_qty", persisted=True)),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sales_order_id", "sku_id", name="uq_inventory_balances_so_sku"),
        sa.CheckConstraint("inbound_qty >= 0", name="ck_inventory_balances_inbound_nn"),
        sa.CheckConstraint("outbound_qty >= 0", name="ck_inventory_balances_outbound_nn"),
        sa.CheckConstraint("inbound_qty >= outbound_qty",
                           name="ck_inventory_balances_available_nn"),
    )
    # (sales_order_id, sku_id) 唯一键已覆盖销售单维度查询与 FK 侧查找;仅补 sku_id 反向过滤。
    op.create_index(op.f("ix_inventory_balances_sku_id"), "inventory_balances", ["sku_id"])

    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("movement_type", sa.String(length=30), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_line_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("qty_delta", sa.Numeric(18, 3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "movement_type IN ('INBOUND_RECEIVE','INBOUND_UNRECEIVE','OUTBOUND_ISSUE')",
            name="ck_inventory_movements_type"),
        sa.CheckConstraint(
            "source_type IN ('INBOUND_ORDER','OUTBOUND_ORDER')",
            name="ck_inventory_movements_source_type"),
        sa.CheckConstraint("qty_delta <> 0", name="ck_inventory_movements_qty_nonzero"),
    )
    op.create_index(op.f("ix_inventory_movements_created_by"), "inventory_movements", ["created_by"])
    op.create_index(op.f("ix_inventory_movements_sku_id"), "inventory_movements", ["sku_id"])
    op.create_index("ix_inventory_movements_so_sku_occurred", "inventory_movements",
                    ["sales_order_id", "sku_id", sa.text("occurred_at DESC"),
                     sa.text("id DESC")])
    op.create_index("ix_inventory_movements_source", "inventory_movements",
                    ["source_type", "source_id", "movement_type", "id"])
    op.create_index("ix_inventory_movements_source_line", "inventory_movements",
                    ["source_type", "source_line_id", "movement_type", "id"])
    op.create_index("ix_inventory_movements_type_occurred", "inventory_movements",
                    ["movement_type", sa.text("occurred_at DESC"), sa.text("id DESC")])

    op.execute(sa.text("""
        INSERT INTO inventory_movements (
            movement_type, source_type, source_id, source_line_id,
            sales_order_id, sku_id, qty_delta, occurred_at, created_by, created_at
        )
        SELECT
            'INBOUND_RECEIVE',
            'INBOUND_ORDER',
            io.id,
            iol.id,
            sol.sales_order_id,
            iol.sku_id,
            iol.qty,
            COALESCE(io.updated_at, io.created_at, now()),
            io.created_by,
            COALESCE(io.updated_at, io.created_at, now())
        FROM inbound_order_lines iol
        JOIN inbound_orders io ON io.id = iol.inbound_order_id
        JOIN purchase_order_lines pol ON pol.id = iol.purchase_order_line_id
        JOIN sales_order_lines sol ON sol.id = pol.source_sales_order_line_id
        WHERE io.status = 'RECEIVED'
    """))
    op.execute(sa.text("""
        INSERT INTO inventory_movements (
            movement_type, source_type, source_id, source_line_id,
            sales_order_id, sku_id, qty_delta, occurred_at, created_by, created_at
        )
        SELECT
            'OUTBOUND_ISSUE',
            'OUTBOUND_ORDER',
            oo.id,
            ool.id,
            oo.sales_order_id,
            ool.sku_id,
            -ool.qty,
            COALESCE(oo.issued_at, oo.updated_at, oo.created_at, now()),
            oo.created_by,
            COALESCE(oo.issued_at, oo.updated_at, oo.created_at, now())
        FROM outbound_order_lines ool
        JOIN outbound_orders oo ON oo.id = ool.outbound_order_id
        WHERE oo.status = 'ISSUED'
    """))
    op.execute(sa.text("""
        INSERT INTO inventory_balances (
            sales_order_id, sku_id, inbound_qty, outbound_qty, created_at, updated_at
        )
        SELECT
            sales_order_id,
            sku_id,
            COALESCE(SUM(CASE WHEN qty_delta > 0 THEN qty_delta ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN qty_delta < 0 THEN -qty_delta ELSE 0 END), 0),
            now(),
            now()
        FROM inventory_movements
        GROUP BY sales_order_id, sku_id
    """))

    op.alter_column("inventory_balances", "created_at", server_default=None)
    op.alter_column("inventory_balances", "updated_at", server_default=None)
    op.alter_column("inventory_movements", "created_at", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_inventory_movements_type_occurred", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_source_line", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_source", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_so_sku_occurred", table_name="inventory_movements")
    op.drop_index(op.f("ix_inventory_movements_sku_id"), table_name="inventory_movements")
    op.drop_index(op.f("ix_inventory_movements_created_by"), table_name="inventory_movements")
    op.drop_table("inventory_movements")

    op.drop_index(op.f("ix_inventory_balances_sku_id"), table_name="inventory_balances")
    op.drop_table("inventory_balances")
