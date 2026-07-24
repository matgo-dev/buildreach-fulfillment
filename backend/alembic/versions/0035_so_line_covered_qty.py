"""0035 sales_order_lines.covered_qty 物化落列(方案C)

采购台选单查询消增长型性能雷:进度=派生值须先算完才能分页,原实现把全部匹配 SO + 订单行
读进内存 Python 算,开销随销售单总数线性涨。落冗余列 covered_qty(已覆盖量物化缓存),采购
三写入口同事务重算写回,列表筛选/排序/分页下推 SQL。行业对标 Odoo qty_delivered / SAP /
NetSuite 在「订单行 vs 已履约量」这个位置默认落列。

单一源头不破坏:compute_covered_qty 仍是唯一计算口径,本列是它的物化缓存。

回填(_run):一条 set-based 全行对齐 UPDATE(非逐行),口径 = compute_covered_qty 的 SQL 版
(Σ 非 CANCELLED PO 行 qty,含 DRAFT)。LEFT JOIN 覆盖**全部** SO 行:无活动覆盖的行同样对齐
到 0,故对任意漂移数据都收敛(真幂等,可直接复用为补账修复);IS DISTINCT FROM 只写不一致行,
迁移时刻列刚建全 0,实际写行数仍受有覆盖行数有界。ADD COLUMN ... DEFAULT '0' 在 PG≥11 是
元数据级(不重写表)。

Revision ID: 0035_so_line_covered_qty
Revises: 0034_retrofit_fk_indexes
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0035_so_line_covered_qty"
down_revision: Union[str, None] = "0034_retrofit_fk_indexes"
branch_labels = None
depends_on = None


# set-based 全行对齐:与 compute_covered_qty(purchase_order_service)口径逐字对应。
# LEFT JOIN 让无活动覆盖的行也对齐 0(不只写有聚合行)→ 对漂移数据同样收敛,重算非自增,真幂等。
_BACKFILL = sa.text("""
    UPDATE sales_order_lines sl
       SET covered_qty = COALESCE(agg.s, 0)
      FROM sales_order_lines s2
      LEFT JOIN (SELECT pol.source_sales_order_line_id AS sid, SUM(pol.qty) AS s
                   FROM purchase_order_lines pol
                   JOIN purchase_orders po ON po.id = pol.purchase_order_id
                  WHERE po.status <> 'CANCELLED'
                  GROUP BY pol.source_sales_order_line_id) agg ON agg.sid = s2.id
     WHERE sl.id = s2.id
       AND sl.covered_qty IS DISTINCT FROM COALESCE(agg.s, 0)
""")


def _run(conn) -> None:
    """data 步骤:把全部 SO 行 covered_qty 对齐真值(含把无活动覆盖的漂移行刷回 0)。
    隔离迁移测试直接驱动本函数验幂等 + 漂移修复。"""
    conn.execute(_BACKFILL)


def upgrade() -> None:
    op.add_column("sales_order_lines", sa.Column(
        "covered_qty", sa.Numeric(18, 3), nullable=False, server_default="0"))
    op.create_check_constraint(
        "ck_slines_covered_nn", "sales_order_lines", "covered_qty >= 0")
    _run(op.get_bind())


def downgrade() -> None:
    op.drop_constraint("ck_slines_covered_nn", "sales_order_lines", type_="check")
    op.drop_column("sales_order_lines", "covered_qty")
