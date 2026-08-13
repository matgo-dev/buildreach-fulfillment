"""0038 出库追加:同柜同 SO 只限制未确认草稿

业务规则收紧/放开:
- 只允许同一销售单 + 同一发运柜同时存在一张 DRAFT 出库单,追加或调整应编辑该草稿。
- 已确认 ISSUED 的出库单不再占唯一槽,允许同柜继续追加一张新的 DRAFT 并再次确认。

Revision ID: 0038_outbound_draft_unique
Revises: 0037_schema_rigor_checks_indexes
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0038_outbound_draft_unique"
down_revision: Union[str, None] = "0037_schema_rigor_checks_indexes"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.drop_index("uq_oborders_shipment_so_active", table_name="outbound_orders")
    op.create_index(
        "uq_oborders_shipment_so_draft",
        "outbound_orders",
        ["shipment_id", "sales_order_id"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
    )


def downgrade() -> None:
    op.drop_index("uq_oborders_shipment_so_draft", table_name="outbound_orders")
    # 若线上已经存在同柜同 SO 多张 ISSUED 追加出库单,降级恢复旧约束会失败,需先人工清理数据。
    op.create_index(
        "uq_oborders_shipment_so_active",
        "outbound_orders",
        ["shipment_id", "sales_order_id"],
        unique=True,
        postgresql_where=sa.text("status <> 'CANCELLED'"),
    )
