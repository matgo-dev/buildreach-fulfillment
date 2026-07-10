"""m1 schema hardening: created_by FK + numeric/range CHECKs + sku_id index

Revision ID: af9ad00ea2cb
Revises: 4aee6cdbe0b6
Create Date: 2026-07-09 23:42:30.793951

DB schema 专项评审(opus, ready-after-fixes)必修/建议修:
- quotation_orders.created_by 补 FK → users.id(原裸 integer,可写入不存在用户)
- quotation_lines 金额/数量/排序 CHECK(应用层 Pydantic 已给 400,这里防直连/回归)
- skus.reference_price / categories.level / sort_order 范围 CHECK
- quotation_lines.sku_id 补索引(FK 未索引 → 溯源/删除校验全表扫)
CHECK 约束 alembic autogenerate 不比对,手工写入。
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'af9ad00ea2cb'
down_revision: Union[str, None] = '4aee6cdbe0b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # sku_id 索引(溯源/删除完整性校验)
    op.create_index(op.f('ix_quotation_lines_sku_id'), 'quotation_lines', ['sku_id'], unique=False)

    # created_by 引用完整性(与旁边 customer_id 对齐)
    op.create_foreign_key('quotation_orders_created_by_fkey', 'quotation_orders', 'users',
                          ['created_by'], ['id'])

    # quotation_lines 金额/数量/排序兜底
    op.create_check_constraint('ck_qlines_qty_pos', 'quotation_lines', 'qty > 0')
    op.create_check_constraint('ck_qlines_unit_price_nn', 'quotation_lines', 'unit_price >= 0')
    op.create_check_constraint('ck_qlines_line_total_nn', 'quotation_lines', 'line_total >= 0')
    op.create_check_constraint('ck_qlines_sort_nn', 'quotation_lines', 'sort_order >= 0')

    # skus 采购参考价非负(可空)
    op.create_check_constraint('ck_skus_ref_price_nn', 'skus',
                               'reference_price IS NULL OR reference_price >= 0')

    # categories 层级/排序
    op.create_check_constraint('ck_categories_level', 'categories', 'level >= 1')
    op.create_check_constraint('ck_categories_sort_nn', 'categories', 'sort_order >= 0')


def downgrade() -> None:
    op.drop_constraint('ck_categories_sort_nn', 'categories', type_='check')
    op.drop_constraint('ck_categories_level', 'categories', type_='check')
    op.drop_constraint('ck_skus_ref_price_nn', 'skus', type_='check')
    op.drop_constraint('ck_qlines_sort_nn', 'quotation_lines', type_='check')
    op.drop_constraint('ck_qlines_line_total_nn', 'quotation_lines', type_='check')
    op.drop_constraint('ck_qlines_unit_price_nn', 'quotation_lines', type_='check')
    op.drop_constraint('ck_qlines_qty_pos', 'quotation_lines', type_='check')
    op.drop_constraint('quotation_orders_created_by_fkey', 'quotation_orders', type_='foreignkey')
    op.drop_index(op.f('ix_quotation_lines_sku_id'), table_name='quotation_lines')
