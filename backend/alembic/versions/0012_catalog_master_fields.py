"""catalog master fields: SPU 加 brand/description/hs_code;SKU 加 重量/长宽高

商品目录主数据补全(见 db/models/spu.py / sku.py 单一源头)。全部为可空列新增 +
SKU 物理属性非负 CHECK。原产地不加(来源侧属性,归采购/批次/报关层)。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0012_catalog_master_fields'
down_revision: Union[str, None] = '0011_spu_lifecycle_draft'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('spus', sa.Column('brand', sa.String(length=100), nullable=True))
    op.add_column('spus', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('spus', sa.Column('hs_code', sa.String(length=20), nullable=True))
    op.add_column('skus', sa.Column('weight_kg', sa.Numeric(12, 3), nullable=True))
    op.add_column('skus', sa.Column('length_cm', sa.Numeric(10, 2), nullable=True))
    op.add_column('skus', sa.Column('width_cm', sa.Numeric(10, 2), nullable=True))
    op.add_column('skus', sa.Column('height_cm', sa.Numeric(10, 2), nullable=True))
    op.create_check_constraint(
        'ck_skus_physical_nonneg', 'skus',
        "(weight_kg IS NULL OR weight_kg >= 0) AND (length_cm IS NULL OR length_cm >= 0) "
        "AND (width_cm IS NULL OR width_cm >= 0) AND (height_cm IS NULL OR height_cm >= 0)")


def downgrade() -> None:
    op.drop_constraint('ck_skus_physical_nonneg', 'skus', type_='check')
    for col in ('height_cm', 'width_cm', 'length_cm', 'weight_kg'):
        op.drop_column('skus', col)
    for col in ('hs_code', 'description', 'brand'):
        op.drop_column('spus', col)
