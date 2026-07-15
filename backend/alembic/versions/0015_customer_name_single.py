"""0015 客户名称去 i18n:name_i18n(JSONB)→ name(单列 String)

客户名是专有名词=身份,非可翻译展示标签,不该建 i18n map(此前 zh 槽即唯一真名,i18n
结构是摆设,搜索/展示也全写死 ['zh'])。回填 name = name_i18n->>'zh'(zh 此前必填非空,
存量必有值)。跨境客户的中文/英文名各按本来面貌存这一列;若将来需第二用途名(开票名/
报关名),另建显式业务字段,仍不用 lang map。

Revision ID: 0015_customer_name_single
Revises: 0014_quotation_lifecycle
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_customer_name_single"
down_revision: Union[str, None] = "0014_quotation_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("name", sa.String(200), nullable=True))
    op.execute("UPDATE customers SET name = name_i18n->>'zh' WHERE name IS NULL")
    op.alter_column("customers", "name", nullable=False)
    op.drop_column("customers", "name_i18n")


def downgrade() -> None:
    op.add_column("customers", sa.Column(
        "name_i18n", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.execute("UPDATE customers SET name_i18n = jsonb_build_object('zh', name) "
               "WHERE name_i18n IS NULL")
    op.alter_column("customers", "name_i18n", nullable=False)
    op.drop_column("customers", "name")
