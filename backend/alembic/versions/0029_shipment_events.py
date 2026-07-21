"""0029 物流:shipment_events 独立新表(主流程第9步,契约 §2)

发运柜离港(DEPARTED)后,运营手动逐条录入在途里程碑(中转/到港)。独立全局表,挂发运柜:
- shipment_id / created_by:FK RESTRICT(被引用行不可硬删);created_by 单列索引(FK 默认加)。
- event_type:里程碑 code(LogisticsMilestone.EVENT_TYPES),DB 不加 CHECK(受控值域,schema 层
  validator 引用 EVENT_TYPES 校验入口即够,更细节点接 API 时改常量无迁移)。
- event_at:Date NOT NULL,事件业务日;location/note nullable;deleted_at 软删(SoftDeleteMixin,
  timezone=True)保留行供追溯。
- 复合索引 (shipment_id, event_at):覆盖轨迹按序 + 派生当前状态取最新 + FK。
- 偏唯一 uq_shipevents_arrived:每柜至多一条活动 ARRIVED(软删的旧到港退出约束,可重录);
  镜像 outbound_orders.uq_oborders_shipment_so_active。

无金额/数量列(无 CHECK 需求);event_at NOT NULL 即够。当前物流状态纯派生,发运柜上不加
current_status 冗余列。

Revision ID: 0029_shipment_events
Revises: 0028_shipment_shipping_fields
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0029_shipment_events"
down_revision: Union[str, None] = "0028_shipment_shipping_fields"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "shipment_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("event_at", sa.Date(), nullable=False),
        sa.Column("location", sa.String(length=60), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipment_orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shipevents_shipment_eventat", "shipment_events",
                    ["shipment_id", "event_at"])
    op.create_index("ix_shipment_events_created_by", "shipment_events", ["created_by"])
    # 每柜至多一条活动 ARRIVED(偏唯一;软删行退出约束)。
    op.create_index("uq_shipevents_arrived", "shipment_events", ["shipment_id"],
                    unique=True,
                    postgresql_where=sa.text("event_type = 'ARRIVED' AND deleted_at IS NULL"))


def downgrade() -> None:
    op.drop_index("uq_shipevents_arrived", table_name="shipment_events")
    op.drop_index("ix_shipment_events_created_by", table_name="shipment_events")
    op.drop_index("ix_shipevents_shipment_eventat", table_name="shipment_events")
    op.drop_table("shipment_events")
