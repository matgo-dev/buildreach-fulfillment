"""0028 发运:shipment_orders 加船务字段 + 装船状态机(契约 §2)

主流程第8步。柜从「组柜容器」扩为承载船务生命周期(装柜/离港):
- 加列(全 nullable,逐步补录):booking_no/vessel_name/voyage_no/bl_no/
  port_of_loading/port_of_discharge(String)+ etd/eta/atd(Date)+ loaded_at(DateTime)。
- CHECK ck_shporders_status 由 2 值('OPEN','CANCELLED')重建为 4 值
  ('OPEN','LOADED','DEPARTED','CANCELLED'),与 model 常量 ShipmentOrderStatus.ALL 同步。

零新表、零新 FK、零新索引:查询路径 = 列表 status 过滤(既有 ix_shipment_orders_status)+
柜号/单号 ilike;柜量 = 月十位数级,100× 后仍小表,不预设索引(升级触发式)。
日期不加 CHECK:atd 早于 etd 是合法现实(提前离港),不可硬约束。发运零金额(红线天然隔离)。

downgrade 前提:2 值 CHECK 还原要求库中**不存在** LOADED/DEPARTED 行,否则 create 约束失败。
仅限 dev 空态/无装船数据回滚;有存量装船单据须先人工迁数据再降级。

Revision ID: 0028_shipment_shipping_fields
Revises: 0027_unit_snapshot_store_code
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0028_shipment_shipping_fields"
down_revision: Union[str, None] = "0027_unit_snapshot_store_code"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_STR_COLUMNS = (
    ("booking_no", 30),
    ("vessel_name", 60),
    ("voyage_no", 20),
    ("bl_no", 40),
    ("port_of_loading", 60),
    ("port_of_discharge", 60),
)
_DATE_COLUMNS = ("etd", "eta", "atd")


def upgrade() -> None:
    for name, length in _STR_COLUMNS:
        op.add_column("shipment_orders",
                      sa.Column(name, sa.String(length=length), nullable=True))
    for name in _DATE_COLUMNS:
        op.add_column("shipment_orders", sa.Column(name, sa.Date(), nullable=True))
    op.add_column("shipment_orders", sa.Column("loaded_at", sa.DateTime(), nullable=True))

    # CHECK 2 值 → 4 值(先 drop 后 create,与 model 常量 ALL 同步)。
    op.drop_constraint("ck_shporders_status", "shipment_orders", type_="check")
    op.create_check_constraint(
        "ck_shporders_status", "shipment_orders",
        "status IN ('OPEN','LOADED','DEPARTED','CANCELLED')")


def downgrade() -> None:
    # 还原 2 值 CHECK。前提:库中无 LOADED/DEPARTED 行(否则约束创建失败)——见 docstring。
    op.drop_constraint("ck_shporders_status", "shipment_orders", type_="check")
    op.create_check_constraint(
        "ck_shporders_status", "shipment_orders", "status IN ('OPEN','CANCELLED')")

    op.drop_column("shipment_orders", "loaded_at")
    for name in reversed(_DATE_COLUMNS):
        op.drop_column("shipment_orders", name)
    for name, _ in reversed(_STR_COLUMNS):
        op.drop_column("shipment_orders", name)
