from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampUpdateMixin


class LogisticsMilestone:
    """物流里程碑(model 层常量,单一源头;不建 lookup 表、DB 不 CHECK event_type)。
    展示骨架顺序:已离港 → 中转 → 到港。

    - DEPARTED(已离港)= **派生自发运柜 atd,不入事件表**(离港单一源头在柜头)。
    - TRANSSHIPMENT / ARRIVED = 手动录入的在途里程碑,入 shipment_events。
    入表 event_type 实际只有 2 个(EVENT_TYPES);更细节点等接承运 API 再往此常量 + 前端
    镜像加,改一行、无迁移、不改表结构。存英文 code,展示走 i18n。
    """
    DEPARTED = "DEPARTED"            # 派生,不入表
    TRANSSHIPMENT = "TRANSSHIPMENT"  # 中转:可选、可重复(入表)
    ARRIVED = "ARRIVED"              # 到港:终点、每柜至多一条活动事件(入表 + 偏唯一)

    # 可录入事件类型值域(schema 层 validator 引用此元组校验;DB 不加 CHECK)。
    EVENT_TYPES = (TRANSSHIPMENT, ARRIVED)
    # 全流程展示骨架顺序(含派生的已离港;前端时间线镜像此序)。
    DISPLAY_ORDER = (DEPARTED, TRANSSHIPMENT, ARRIVED)


class ShipmentEvent(Base, TimestampUpdateMixin, SoftDeleteMixin):
    """物流轨迹事件(挂发运柜)。货离港后在途里程碑的手动录入(P0);未来接承运 API 灌更细
    节点走同一张表。无红线字段(无成本/供应商/售价)。软删保留行供追溯。

    「当前物流状态」纯派生(取 event_at 最新活动事件),发运柜上不落 current_status 冗余列。
    """
    __tablename__ = "shipment_events"
    __table_args__ = (
        # 覆盖「取某柜轨迹按序」+「派生当前状态取最新」+ FK(首列 shipment_id 已满足)。
        Index("ix_shipevents_shipment_eventat", "shipment_id", "event_at"),
        # 「每柜至多一条活动到港」落 DB 最强层:偏唯一只约束活动的 ARRIVED 行(软删的旧到港
        # 退出约束,可重录)。镜像 outbound_orders.uq_oborders_shipment_so_active。
        Index("uq_shipevents_arrived", "shipment_id", unique=True,
              postgresql_where=text("event_type = 'ARRIVED' AND deleted_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 挂柜。RESTRICT:被事件引用的柜不可硬删;首列已被复合索引覆盖(不再单列建 FK 索引)。
    shipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("shipment_orders.id", ondelete="RESTRICT"), nullable=False)
    # 里程碑 code(LogisticsMilestone.EVENT_TYPES 之一)。DB 不加 CHECK(受控值域框架:
    # schema 层 validator 引用 EVENT_TYPES 校验入口即够);展示走 i18n。
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 事件发生业务日(非录入时刻),与柜船期字段 etd/eta/atd 同粒度。service 校验 ≥ atd。
    event_at: Mapped[date] = mapped_column(Date, nullable=False)
    # 地点自由文本(镜像港口字段先例:唯一消费者=展示;消费者出现再升 UN/LOCODE)。
    location: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 录入人(审计归属);改/删动作走 audit_logs,不加 updated_by。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
