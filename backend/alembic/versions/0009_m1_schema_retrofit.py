"""m1 schema retrofit —— 回补 M1 地基约束(独立 DB 评审 5 项 should-fix)

对齐 PR#2 商品表(skus/spus)的严谨度,把 M1 地基表的约束补齐:
- customers.status          → CHECK IN ('ACTIVE','INACTIVE')
- quotation_orders.currency → CHECK ISO4217 三字母大写(锁死币种格式,不存中文/自由串)
- quotation_orders.status   → CHECK IN ('DRAFT')(只 bound 当前值;M2 增状态时同步扩)
- quotation_orders 两个 FK  → 显式 ON DELETE RESTRICT
- quotation_lines 两个 FK   → order CASCADE(组合)/ sku RESTRICT(溯源)
- customers.preferred_language → 重命名 quote_language + 收窄 String(10) + CHECK 三选一
  (原 BCP47 自由串 String(35) 唯一消费者是 resolve_quote_language 映射;报价语言业务上
   只有 zh/en/sw 三选一,砍掉宽存窄用的中间层,值域收口到单一源头 core.languages)
- quotation_orders.language / quotation_lines.language → CHECK IN ('zh','en','sw')

约束层变更 + 一处列重命名/收窄,不改行数据。
前置:若生产已有 currency 小写/中文,或 preferred_language 存了 BCP47 细码(zh-CN 等),
须先清洗/映射到 zh/en/sw 再升级,否则 CHECK 校验失败。本仓迁移谱系此前无该数据。
FK 约束名用 PG 默认命名 <table>_<col>_fkey(原迁移未显式命名,由 PG 生成)。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

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

    # ── 报价语言收口:preferred_language(BCP47 自由串)→ quote_language(三选一)──
    op.alter_column('customers', 'preferred_language', new_column_name='quote_language',
                    existing_type=sa.String(35), type_=sa.String(10), existing_nullable=True)
    op.create_check_constraint(
        'ck_customers_quote_language', 'customers',
        "quote_language IS NULL OR quote_language IN ('zh','en','sw')")
    op.create_check_constraint(
        'ck_qorders_language', 'quotation_orders', "language IN ('zh','en','sw')")
    op.create_check_constraint(
        'ck_qlines_language', 'quotation_lines', "language IN ('zh','en','sw')")

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

    # 报价语言收口还原
    op.drop_constraint('ck_qlines_language', 'quotation_lines', type_='check')
    op.drop_constraint('ck_qorders_language', 'quotation_orders', type_='check')
    op.drop_constraint('ck_customers_quote_language', 'customers', type_='check')
    op.alter_column('customers', 'quote_language', new_column_name='preferred_language',
                    existing_type=sa.String(10), type_=sa.String(35), existing_nullable=True)

    op.drop_constraint('ck_qorders_status', 'quotation_orders', type_='check')
    op.drop_constraint('ck_qorders_currency_iso4217', 'quotation_orders', type_='check')
    op.drop_constraint('ck_customers_status', 'customers', type_='check')
