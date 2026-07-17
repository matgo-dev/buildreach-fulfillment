"""0025 出库:shipment_orders + outbound_orders + outbound_order_lines(契约 §1.1/1.2/1.3)

主流程第6步。出库单 = 销售单 N:1 × 发运单(柜)N:1 的桥;行不跨 SO、不跨柜。
- shipment_orders  = 柜(本步最小骨架,组柜容器);状态机 OPEN→{CANCELLED}。
- outbound_orders  = 出库单头;状态机 DRAFT→{ISSUED,CANCELLED} / ISSUED→{DRAFT};
                     偏唯一 UNIQUE(shipment_id, sales_order_id) WHERE status<>'CANCELLED'
                     =「一柜内每来源 SO 各一张」落 DB。无价格 / 成本列(纯仓单)。
- outbound_order_lines = 行;不复制快照(经 join SO 行展示,SO 行冻结单一源头)。

FK 引用列全量索引(owner 硬规则,偏唯一不替代);行→单 CASCADE、溯源/审计 RESTRICT。
应收(receivables)独立生于 0026(财务域全局表不生在功能迁移里,镜像 payable 0020 先例)。

Revision ID: 0025_outbound
Revises: 0024_quotation_so_sku_unique
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0025_outbound"
down_revision: Union[str, None] = "0024_quotation_so_sku_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- shipment_orders(柜,最小骨架)----
    op.create_table(
        "shipment_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("container_no", sa.String(length=20), nullable=True),
        sa.Column("container_type", sa.String(length=10), nullable=True),
        sa.Column("seal_no", sa.String(length=30), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        # 本步转移矩阵 OPEN→{CANCELLED};发运步扩展 OPEN→LOADED→…。
        sa.CheckConstraint("status IN ('OPEN','CANCELLED')", name="ck_shporders_status"),
    )
    op.create_index(op.f("ix_shipment_orders_no"), "shipment_orders", ["no"], unique=True)
    op.create_index(op.f("ix_shipment_orders_created_by"), "shipment_orders", ["created_by"])
    op.create_index(op.f("ix_shipment_orders_status"), "shipment_orders", ["status"])

    # ---- outbound_orders(出库单头)----
    op.create_table(
        "outbound_orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("no", sa.String(length=30), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 溯源 RESTRICT:SO / 柜被出库单引用时不可硬删;建单人 RESTRICT。
        sa.ForeignKeyConstraint(["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipment_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('DRAFT','ISSUED','CANCELLED')", name="ck_oborders_status"),
    )
    op.create_index(op.f("ix_outbound_orders_no"), "outbound_orders", ["no"], unique=True)
    op.create_index(op.f("ix_outbound_orders_sales_order_id"), "outbound_orders",
                    ["sales_order_id"])
    op.create_index(op.f("ix_outbound_orders_shipment_id"), "outbound_orders", ["shipment_id"])
    op.create_index(op.f("ix_outbound_orders_created_by"), "outbound_orders", ["created_by"])
    # 列表默认 status tab 过滤 + created_at DESC 排序(镜像 ix_inborders_status_created)。
    op.create_index("ix_oborders_status_created", "outbound_orders",
                    ["status", sa.text("created_at DESC")])
    # 偏唯一:一柜内每来源 SO 至多一张活动出库单(取消行退出,可重开)。
    op.create_index("uq_oborders_shipment_so_active", "outbound_orders",
                    ["shipment_id", "sales_order_id"], unique=True,
                    postgresql_where=sa.text("status <> 'CANCELLED'"))

    # ---- outbound_order_lines(出库单行)----
    op.create_table(
        "outbound_order_lines",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("outbound_order_id", sa.Integer(), nullable=False),
        sa.Column("sales_order_line_id", sa.Integer(), nullable=False),
        sa.Column("sku_id", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Numeric(precision=18, scale=3), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # 行是单的组合成分:单删则行随删(CASCADE);SO 行 / sku 溯源 RESTRICT。
        sa.ForeignKeyConstraint(["outbound_order_id"], ["outbound_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sales_order_line_id"], ["sales_order_lines.id"],
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sku_id"], ["skus.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("qty > 0", name="ck_oblines_qty_pos"),
        # 同单同 SO 行至多一行(镜像入库行 uq_inblines_inb_poline)。
        sa.UniqueConstraint("outbound_order_id", "sales_order_line_id",
                            name="uq_oblines_ob_soline"),
    )
    op.create_index(op.f("ix_outbound_order_lines_outbound_order_id"), "outbound_order_lines",
                    ["outbound_order_id"])
    op.create_index(op.f("ix_outbound_order_lines_sales_order_line_id"), "outbound_order_lines",
                    ["sales_order_line_id"])
    op.create_index(op.f("ix_outbound_order_lines_sku_id"), "outbound_order_lines", ["sku_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_outbound_order_lines_sku_id"), table_name="outbound_order_lines")
    op.drop_index(op.f("ix_outbound_order_lines_sales_order_line_id"),
                  table_name="outbound_order_lines")
    op.drop_index(op.f("ix_outbound_order_lines_outbound_order_id"),
                  table_name="outbound_order_lines")
    op.drop_table("outbound_order_lines")

    op.drop_index("uq_oborders_shipment_so_active", table_name="outbound_orders")
    op.drop_index("ix_oborders_status_created", table_name="outbound_orders")
    op.drop_index(op.f("ix_outbound_orders_created_by"), table_name="outbound_orders")
    op.drop_index(op.f("ix_outbound_orders_shipment_id"), table_name="outbound_orders")
    op.drop_index(op.f("ix_outbound_orders_sales_order_id"), table_name="outbound_orders")
    op.drop_index(op.f("ix_outbound_orders_no"), table_name="outbound_orders")
    op.drop_table("outbound_orders")

    op.drop_index(op.f("ix_shipment_orders_status"), table_name="shipment_orders")
    op.drop_index(op.f("ix_shipment_orders_created_by"), table_name="shipment_orders")
    op.drop_index(op.f("ix_shipment_orders_no"), table_name="shipment_orders")
    op.drop_table("shipment_orders")
