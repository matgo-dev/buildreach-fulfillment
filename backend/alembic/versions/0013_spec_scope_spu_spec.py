"""spu/sku 规格分层: category_spec_attributes.scope + spus.spec_jsonb

见 docs/履约系统/2026-07-13-0416-SPU-SKU规格分层-设计契约.md。
- scope 区分产品级(spu,一个 SPU 内恒定)/ 变体轴(sku,SKU 间区分);默认 'sku' 向后兼容。
- spus 加 spec_jsonb 承载产品级规格值(形状同 skus.spec_jsonb)。
两处均为既有 catalog 特性表 ALTER;既有行由 server_default 回填(表可能已有数据)。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0013_spec_scope_spu_spec'
down_revision: Union[str, None] = '0012_catalog_master_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'category_spec_attributes',
        sa.Column('scope', sa.String(length=20), nullable=False, server_default='sku'))
    op.create_check_constraint(
        'ck_cat_spec_attr_scope', 'category_spec_attributes', "scope IN ('spu','sku')")
    op.add_column(
        'spus',
        sa.Column('spec_jsonb', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'[]'::jsonb")))
    # SPU 维度搜索(名+品牌+产品级规格),与 skus.search_text 同款 pg_trgm GIN。
    op.add_column('spus', sa.Column('search_text', sa.Text(), nullable=False, server_default=''))
    op.create_index('ix_spus_search_text_trgm', 'spus', ['search_text'], unique=False,
                    postgresql_using='gin', postgresql_ops={'search_text': 'gin_trgm_ops'})


def downgrade() -> None:
    op.drop_index('ix_spus_search_text_trgm', table_name='spus')
    op.drop_column('spus', 'search_text')
    op.drop_column('spus', 'spec_jsonb')
    op.drop_constraint('ck_cat_spec_attr_scope', 'category_spec_attributes', type_='check')
    op.drop_column('category_spec_attributes', 'scope')
