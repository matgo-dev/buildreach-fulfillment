"""0014 报价生命周期:status 四态 + total_amount/salesperson_id/summary(orders)+ remark(lines)

把 M1 报价草稿切片补成完整状态机。存量行回填:salesperson_id=created_by、total_amount=Σ行。
status CHECK 先 drop 再建(Postgres 不能原地改 CHECK)。

Revision ID: 0014_quotation_lifecycle
Revises: 0013_spec_scope_spu_spec
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_quotation_lifecycle"
down_revision: Union[str, None] = "0013_spec_scope_spu_spec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 加列:salesperson_id 先 nullable;total_amount 用 server_default 过渡建列;summary/remark 可空。
    op.add_column("quotation_orders", sa.Column("salesperson_id", sa.Integer(), nullable=True))
    op.add_column("quotation_orders", sa.Column(
        "total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"))
    op.add_column("quotation_orders", sa.Column("summary", sa.String(180), nullable=True))
    op.add_column("quotation_lines", sa.Column("remark", sa.Text(), nullable=True))

    # 2) 回填存量行(口径同 service 默认:报价人=建单人;表头总额=行之和)。
    op.execute("UPDATE quotation_orders SET salesperson_id = created_by "
               "WHERE salesperson_id IS NULL")
    op.execute("UPDATE quotation_orders o SET total_amount = "
               "(SELECT COALESCE(SUM(line_total), 0) FROM quotation_lines "
               "WHERE quotation_order_id = o.id)")

    # 3) salesperson_id 收紧 NOT NULL + FK RESTRICT;total_amount 去过渡 server_default。
    op.alter_column("quotation_orders", "salesperson_id", nullable=False)
    op.create_foreign_key("fk_qorders_salesperson", "quotation_orders", "users",
                          ["salesperson_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_quotation_orders_salesperson_id", "quotation_orders", ["salesperson_id"])
    op.alter_column("quotation_orders", "total_amount", server_default=None)

    # 4) CHECK(total≥0)、复合索引、status CHECK 先 drop 再建四值。
    op.create_check_constraint("ck_qorders_total_amount_nn", "quotation_orders",
                               "total_amount >= 0")
    op.create_index("ix_qorders_status_created", "quotation_orders",
                    ["status", sa.text("created_at DESC")])
    op.drop_constraint("ck_qorders_status", "quotation_orders", type_="check")
    op.create_check_constraint(
        "ck_qorders_status", "quotation_orders",
        "status IN ('DRAFT','LOCKED','CONVERTED','VOID')")


def downgrade() -> None:
    # 存量若已有 LOCKED/CONVERTED/VOID 行,CHECK 收窄会挡下——标准现象。
    op.drop_constraint("ck_qorders_status", "quotation_orders", type_="check")
    op.create_check_constraint("ck_qorders_status", "quotation_orders", "status IN ('DRAFT')")
    op.drop_index("ix_qorders_status_created", table_name="quotation_orders")
    op.drop_constraint("ck_qorders_total_amount_nn", "quotation_orders", type_="check")
    op.drop_index("ix_quotation_orders_salesperson_id", table_name="quotation_orders")
    op.drop_constraint("fk_qorders_salesperson", "quotation_orders", type_="foreignkey")
    op.drop_column("quotation_lines", "remark")
    op.drop_column("quotation_orders", "summary")
    op.drop_column("quotation_orders", "total_amount")
    op.drop_column("quotation_orders", "salesperson_id")
