"""0021 SO 整单取消:CANCELLED 态 + 取消留痕 + 偏唯一改造(契约 2026-07-16-0707 v2)

- status CHECK 扩边 CONFIRMED|CANCELLED + 留痕一致性 CHECK((status='CANCELLED')=(cancelled_at IS NOT NULL));
- UNIQUE(source_quotation_id) → 活动行偏唯一(WHERE status <> 'CANCELLED'):取消后报价回 LOCKED
  可重转,新活动行与留痕行共存(同款先例 uq_payables_inbound_active)+ 补全量 FK 索引;
- 行级 UNIQUE(source_quotation_line_id) → 复合 UNIQUE(sales_order_id, source_quotation_line_id):
  同单防重复,跨单(重转)放行 + 补单列 FK 索引;
- 加列 cancelled_at / cancelled_by(FK→users)/ cancel_reason。

downgrade 数据前提:不存在「取消+重转」数据(同 source_quotation_id 多行 / 同报价行入多单)。
存在时唯一约束重建会失败——**失败为预期**,不静默删数据;需先人工清理(删 CANCELLED 留痕行
或归并)再重跑 downgrade。

Revision ID: 0021_so_cancel
Revises: 0020_payable
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021_so_cancel"
down_revision: Union[str, None] = "0020_payable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- sales_orders:留痕列 ----
    op.add_column("sales_orders", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    op.add_column("sales_orders", sa.Column("cancelled_by", sa.Integer(), nullable=True))
    op.add_column("sales_orders", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.create_foreign_key("sales_orders_cancelled_by_fkey", "sales_orders", "users",
                          ["cancelled_by"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_sales_orders_cancelled_by", "sales_orders", ["cancelled_by"])

    # ---- sales_orders:状态 CHECK 扩边 + 留痕一致性 ----
    op.drop_constraint("ck_sorders_status", "sales_orders", type_="check")
    op.create_check_constraint("ck_sorders_status", "sales_orders",
                               "status IN ('CONFIRMED','CANCELLED')")
    op.create_check_constraint("ck_sorders_cancel_trace", "sales_orders",
                               "(status = 'CANCELLED') = (cancelled_at IS NOT NULL)")

    # ---- sales_orders:UNIQUE → 活动行偏唯一 + 全量 FK 索引 ----
    op.drop_constraint("uq_sorders_source_quotation", "sales_orders", type_="unique")
    op.create_index("ix_sales_orders_source_quotation_id", "sales_orders",
                    ["source_quotation_id"])
    op.create_index("uq_sorders_source_quotation_active", "sales_orders",
                    ["source_quotation_id"], unique=True,
                    postgresql_where=sa.text("status <> 'CANCELLED'"))

    # ---- sales_order_lines:单列 UNIQUE → 复合 UNIQUE + 单列 FK 索引 ----
    op.drop_constraint("uq_slines_source_quotation_line", "sales_order_lines", type_="unique")
    op.create_index("ix_sales_order_lines_source_quotation_line_id", "sales_order_lines",
                    ["source_quotation_line_id"])
    op.create_index("uq_slines_order_source_line", "sales_order_lines",
                    ["sales_order_id", "source_quotation_line_id"], unique=True)


def downgrade() -> None:
    # 数据前提见模块 docstring:存在重转数据时,唯一约束重建将失败(预期),先人工清理。
    op.drop_index("uq_slines_order_source_line", table_name="sales_order_lines")
    op.drop_index("ix_sales_order_lines_source_quotation_line_id",
                  table_name="sales_order_lines")
    op.create_unique_constraint("uq_slines_source_quotation_line", "sales_order_lines",
                                ["source_quotation_line_id"])

    op.drop_index("uq_sorders_source_quotation_active", table_name="sales_orders")
    op.drop_index("ix_sales_orders_source_quotation_id", table_name="sales_orders")
    op.create_unique_constraint("uq_sorders_source_quotation", "sales_orders",
                                ["source_quotation_id"])

    op.drop_constraint("ck_sorders_cancel_trace", "sales_orders", type_="check")
    op.drop_constraint("ck_sorders_status", "sales_orders", type_="check")
    op.create_check_constraint("ck_sorders_status", "sales_orders",
                               "status IN ('CONFIRMED')")

    op.drop_index("ix_sales_orders_cancelled_by", table_name="sales_orders")
    op.drop_constraint("sales_orders_cancelled_by_fkey", "sales_orders", type_="foreignkey")
    op.drop_column("sales_orders", "cancel_reason")
    op.drop_column("sales_orders", "cancelled_by")
    op.drop_column("sales_orders", "cancelled_at")
