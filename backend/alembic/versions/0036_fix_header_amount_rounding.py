"""0036 修正报价/采购/销售头表 total_amount 舍入口径漂移

历史缺陷:报价 _reconcile_lines / 采购 _add_lines 的行额未 quantize 即求和,表头按「原始乘积
求和后舍一次」落库,而行 line_total 列是 DB Numeric(18,2) 逐行四舍。两个口径可差分位(如 3 行
0.99×1.115:Σ 逐行 2dp=3.30,原始求和舍一次=3.31),并经转销售冻结进 sales_orders.total_amount,
与出库侧逐行 quantize 生成的应收合计错位、令 SO 永远收不清。代码侧已改为逐行 quantize(与入库/
出库同口径),本迁移把三张头表存量修回 = Σ(行 line_total)。

回填(_run):三条 set-based 全行对齐 UPDATE(非逐行),口径 = Σ 已存 2dp 行额(line_total 列即
DB 2dp,与新代码逐行 quantize 结果一致)。IS DISTINCT FROM 只写口径不一致的头,已正确的行不动;
无行的草稿头对齐 0(COALESCE)。correlated 子查询走行表 FK 索引,有界。真幂等,可复用为补账修复。

downgrade:no-op。旧值是错误口径的产物,不可也不应恢复(数据修正类迁移,镜像 0022 的无 op 姿态)。

Revision ID: 0036_fix_header_amount_rounding
Revises: 0035_so_line_covered_qty
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0036_fix_header_amount_rounding"
down_revision: Union[str, None] = "0035_so_line_covered_qty"
branch_labels = None
depends_on = None


# (头表, 行表, 外键列):行额 line_total 已是 DB 2dp,表头 = Σ 行额即正确口径。
_TABLES = (
    ("quotation_orders", "quotation_lines", "quotation_order_id"),
    ("purchase_orders", "purchase_order_lines", "purchase_order_id"),
    ("sales_orders", "sales_order_lines", "sales_order_id"),
)


def _run(conn) -> None:
    for header, line, fk in _TABLES:
        conn.execute(sa.text(f"""
            UPDATE {header} h
               SET total_amount = COALESCE(
                   (SELECT SUM(l.line_total) FROM {line} l WHERE l.{fk} = h.id), 0)
             WHERE h.total_amount IS DISTINCT FROM COALESCE(
                   (SELECT SUM(l.line_total) FROM {line} l WHERE l.{fk} = h.id), 0)
        """))


def upgrade() -> None:
    _run(op.get_bind())


def downgrade() -> None:
    """no-op:旧 total_amount 是错误舍入口径的产物,不可逆(数据修正类迁移)。"""
