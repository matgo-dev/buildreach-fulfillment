from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ShipmentOrderStatus:
    OPEN = "OPEN"
    CANCELLED = "CANCELLED"
    ALL = (OPEN, CANCELLED)


# 状态机单一源头(model 层常量)。发运单 = 柜:本步只承担「组柜容器」角色,组柜期 OPEN。
# 本步转移矩阵 OPEN→{CANCELLED};订舱/装船状态(OPEN→LOADED→…)归发运步系统性扩展,
# 不预造投机态。取消守卫(柜下有活动出库单则拒)在 service 层(42001)。
SHIPMENT_ORDER_TRANSITIONS: dict[str, set[str]] = {
    ShipmentOrderStatus.OPEN: {ShipmentOrderStatus.CANCELLED},
    ShipmentOrderStatus.CANCELLED: set(),
}
# 可编辑集:仅组柜中(改柜号/柜型/封条)。无硬删——柜是真实容器,只取消不删。
SHIPMENT_ORDER_EDITABLE_STATUSES: set[str] = {ShipmentOrderStatus.OPEN}


class ShipmentOrder(Base, TimestampUpdateMixin):
    """发运单(=柜,本步最小骨架)。订舱/船名航次/港/ETD/ETA/提单/报关等船务字段
    与装船状态机归发运步加列扩展;无红线字段(成本/供应商/售价)。"""
    __tablename__ = "shipment_orders"
    __table_args__ = (
        # 状态 DB 兜底,bound 到状态机全集(单一源头 ShipmentOrderStatus.ALL)。
        CheckConstraint("status IN ('OPEN','CANCELLED')", name="ck_shporders_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # 柜号:组柜期可空,OPEN 期可改。柜型 code(20GP/40GP/40HQ/45HQ)= 应用层枚举 + 前端镜像,
    # 不落 CHECK(受控值域框架:消费者仅表单校验)。
    container_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    container_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    seal_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 列表状态过滤路径。index=True 走默认命名(ix_shipment_orders_status),与迁移 0025 同名
    # (显式短名会与迁移漂移成同索引两名,测试库/真实库各一套)。
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ShipmentOrderStatus.OPEN, index=True)
    # 建单人(审计归属);取消动作走 audit_logs,不加 cancelled_by(遵审计归属判据 / 业务单据不放 updated_by)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
