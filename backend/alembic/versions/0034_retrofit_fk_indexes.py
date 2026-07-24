"""0034 回补 FK 索引 + Category 自引用 ondelete 显式化(跨增量走查遗留)

整仓走查 P2(FK 索引默认加,owner 硬规则 2026-07-16 确立):规则确立前落地的最早 5 张
单据头表 created_by / voided_by 从未回补索引,而 2026-07 起的新表(shipment/outbound/
receivable/receipt/payment/customs/attachment)均已规范索引 —— 此迁移补齐历史缺口:

  quotation_orders.created_by / sales_orders.created_by / purchase_orders.created_by /
  inbound_orders.created_by / payables.created_by / payables.voided_by

顺带 nit:categories.parent_code 自引用 FK 原未显式 ondelete(0002 默认 NO ACTION),
与同库其它对 categories 的引用(spu.category_code / category_spec_attribute.category_code
均 RESTRICT)不一致 —— 改为显式 RESTRICT(categories 实践只软删 is_active,功能等价,纯风格统一)。

纯加索引 + 改约束,无数据迁移、无数据风险。

Revision ID: 0034_retrofit_fk_indexes
Revises: 0033_refresh_tokens
"""
from __future__ import annotations

from typing import Union

from alembic import op

revision: str = "0034_retrofit_fk_indexes"
down_revision: Union[str, None] = "0033_refresh_tokens"
branch_labels = None
depends_on = None

# (表, 列)——回补的 FK 索引;索引名走 op.f 约定 ix_<table>_<col>。
_FK_INDEXES = [
    ("quotation_orders", "created_by"),
    ("sales_orders", "created_by"),
    ("purchase_orders", "created_by"),
    ("inbound_orders", "created_by"),
    ("payables", "created_by"),
    ("payables", "voided_by"),
]

# categories.parent_code 自引用 FK:0002 CREATE TABLE 内联无显式名 → PG 默认 <table>_<col>_fkey。
_CAT_FK = "categories_parent_code_fkey"


def upgrade() -> None:
    for table, col in _FK_INDEXES:
        op.create_index(op.f(f"ix_{table}_{col}"), table, [col])
    # 自引用 FK 改显式 RESTRICT(先删默认约束再按同键重建)。
    op.drop_constraint(_CAT_FK, "categories", type_="foreignkey")
    op.create_foreign_key(_CAT_FK, "categories", "categories",
                          ["parent_code"], ["code"], ondelete="RESTRICT")


def downgrade() -> None:
    op.drop_constraint(_CAT_FK, "categories", type_="foreignkey")
    op.create_foreign_key(_CAT_FK, "categories", "categories",
                          ["parent_code"], ["code"])
    for table, col in _FK_INDEXES:
        op.drop_index(op.f(f"ix_{table}_{col}"), table_name=table)
