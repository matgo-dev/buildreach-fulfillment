"""0024 报价/销售单行 SKU 唯一(上游 retrofit,契约 §0-11 / §1)

业务公理:报价 / SO = 线下已定需求录入,一 SKU 一价,业务中不存在阶梯价 / 同 SKU 多价
(参照 Medusa/Saleor/Vendure 行=variant 唯一)。落 DB 最强层:
- quotation_lines  补 UNIQUE(quotation_order_id, sku_id)
- sales_order_lines 补 UNIQUE(sales_order_id, sku_id)
(SO,SKU) 粒度 == SO 行粒度,使确认出库的行级金额闸结构性消失。

升级前先 set-based 断言无重复数据:有脏数据 **fail loudly** 列出冲突键,不静默去重
(本地 dev 数据有界)。downgrade 删约束。

Revision ID: 0024_quotation_so_sku_unique
Revises: 0023_account_lockout
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0024_quotation_so_sku_unique"
down_revision: Union[str, None] = "0023_account_lockout"
branch_labels = None
depends_on = None


def _assert_no_dupes(bind, table: str, parent_col: str) -> None:
    """set-based 断言:同 (parent, sku) 无重复行。有则 raise 列出冲突键,不静默处理。"""
    rows = bind.execute(sa.text(
        f"SELECT {parent_col} AS pid, sku_id, COUNT(*) AS n "
        f"FROM {table} GROUP BY {parent_col}, sku_id HAVING COUNT(*) > 1 "
        f"ORDER BY {parent_col}, sku_id"
    )).all()
    if rows:
        detail = ", ".join(f"({parent_col}={r.pid}, sku_id={r.sku_id}, count={r.n})" for r in rows)
        raise RuntimeError(
            f"{table} 存在同 SKU 重复行,无法建立唯一约束(需先人工归并,不静默去重): {detail}")


def upgrade() -> None:
    bind = op.get_bind()
    _assert_no_dupes(bind, "quotation_lines", "quotation_order_id")
    _assert_no_dupes(bind, "sales_order_lines", "sales_order_id")

    op.create_unique_constraint(
        "uq_qlines_order_sku", "quotation_lines", ["quotation_order_id", "sku_id"])
    op.create_unique_constraint(
        "uq_slines_order_sku", "sales_order_lines", ["sales_order_id", "sku_id"])


def downgrade() -> None:
    op.drop_constraint("uq_slines_order_sku", "sales_order_lines", type_="unique")
    op.drop_constraint("uq_qlines_order_sku", "quotation_lines", type_="unique")
