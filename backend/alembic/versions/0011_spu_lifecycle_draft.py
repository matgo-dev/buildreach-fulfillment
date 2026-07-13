"""spu lifecycle: 商品状态机加 DRAFT(草稿)—— 扩 ck_spus_status 值域

商品生命周期由二态(ACTIVE/INACTIVE)扩为三态 DRAFT/ACTIVE/INACTIVE(见 db/models/spu.py
SpuStatus)。语义 = 能否被下游(报价)选用,非对外可见:新建默认 DRAFT,补齐带价在售 SKU
后启用→ACTIVE,淘汰→INACTIVE。

本迁移只扩 CHECK 值域一处:
- status 无 server_default(建表时即 Python 层 default,见 0007);默认值改 DRAFT 落在
  model `SpuStatus.DRAFT`,与 create_all 单一源头,DDL 不复制一份 server_default。
- 现有行 status 不回填(生产已上架的保持 ACTIVE;DRAFT 只对新建生效)。
- SKU 仍二态,ck_skus_status 不动。

downgrade 收回 DRAFT:**前置**须无 status='DRAFT' 的行,否则旧 CHECK 校验失败
(与本仓其它 CHECK 迁移同口径,清洗后再降级)。
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0011_spu_lifecycle_draft'
down_revision: Union[str, None] = '0010_product_images'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('ck_spus_status', 'spus', type_='check')
    op.create_check_constraint(
        'ck_spus_status', 'spus', "status IN ('DRAFT','ACTIVE','INACTIVE')")


def downgrade() -> None:
    op.drop_constraint('ck_spus_status', 'spus', type_='check')
    op.create_check_constraint(
        'ck_spus_status', 'spus', "status IN ('ACTIVE','INACTIVE')")
