"""m1 schema retrofit —— 回补 M1 地基约束(独立 DB 评审 5 项 should-fix)

对齐 PR#2 商品表(skus/spus)的严谨度,把 M1 地基表的约束补齐:
- customers.status          → CHECK IN ('ACTIVE','INACTIVE')
- quotation_orders.currency → CHECK ISO4217 三字母大写(锁死币种格式,不存中文/自由串)
- quotation_orders.status   → CHECK IN ('DRAFT')(只 bound 当前值;M2 增状态时同步扩)
- quotation_orders 两个 FK  → 显式 ON DELETE RESTRICT
- quotation_lines 两个 FK   → order CASCADE(组合)/ sku RESTRICT(溯源)

全为约束层变更(additive CHECK + FK 重建),不改列/不改数据。
前置:若生产已有 currency 小写/中文等非法值,须先清洗再升级,否则 CHECK 校验失败。
FK 约束名用 PG 默认命名 <table>_<col>_fkey(原迁移未显式命名,由 PG 生成)。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd9f1a2b3c4e5'
down_revision: Union[str, None] = '4aee6cdbe0b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── CHECK 兜底 ──
    op.create_check_constraint(
        'ck_customers_status', 'customers', "status IN ('ACTIVE','INACTIVE')")
    op.create_check_constraint(
        'ck_qorders_currency_iso4217', 'quotation_orders', "currency ~ '^[A-Z]{3}$'")
    op.create_check_constraint(
        'ck_qorders_status', 'quotation_orders', "status IN ('DRAFT')")

    # ── FK 重建,补显式 ondelete(原为隐式 NO ACTION)──
    op.drop_constraint('quotation_orders_customer_id_fkey', 'quotation_orders', type_='foreignkey')
    op.create_foreign_key('quotation_orders_customer_id_fkey', 'quotation_orders',
                          'customers', ['customer_id'], ['id'], ondelete='RESTRICT')
    op.drop_constraint('quotation_orders_created_by_fkey', 'quotation_orders', type_='foreignkey')
    op.create_foreign_key('quotation_orders_created_by_fkey', 'quotation_orders',
                          'users', ['created_by'], ['id'], ondelete='RESTRICT')

    op.drop_constraint('quotation_lines_quotation_order_id_fkey', 'quotation_lines', type_='foreignkey')
    op.create_foreign_key('quotation_lines_quotation_order_id_fkey', 'quotation_lines',
                          'quotation_orders', ['quotation_order_id'], ['id'], ondelete='CASCADE')
    op.drop_constraint('quotation_lines_sku_id_fkey', 'quotation_lines', type_='foreignkey')
    op.create_foreign_key('quotation_lines_sku_id_fkey', 'quotation_lines',
                          'skus', ['sku_id'], ['id'], ondelete='RESTRICT')


def downgrade() -> None:
    # FK 还原为隐式 NO ACTION
    op.drop_constraint('quotation_lines_sku_id_fkey', 'quotation_lines', type_='foreignkey')
    op.create_foreign_key('quotation_lines_sku_id_fkey', 'quotation_lines',
                          'skus', ['sku_id'], ['id'])
    op.drop_constraint('quotation_lines_quotation_order_id_fkey', 'quotation_lines', type_='foreignkey')
    op.create_foreign_key('quotation_lines_quotation_order_id_fkey', 'quotation_lines',
                          'quotation_orders', ['quotation_order_id'], ['id'])
    op.drop_constraint('quotation_orders_created_by_fkey', 'quotation_orders', type_='foreignkey')
    op.create_foreign_key('quotation_orders_created_by_fkey', 'quotation_orders',
                          'users', ['created_by'], ['id'])
    op.drop_constraint('quotation_orders_customer_id_fkey', 'quotation_orders', type_='foreignkey')
    op.create_foreign_key('quotation_orders_customer_id_fkey', 'quotation_orders',
                          'customers', ['customer_id'], ['id'])

    op.drop_constraint('ck_qorders_status', 'quotation_orders', type_='check')
    op.drop_constraint('ck_qorders_currency_iso4217', 'quotation_orders', type_='check')
    op.drop_constraint('ck_customers_status', 'customers', type_='check')
