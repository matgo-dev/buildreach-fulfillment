from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class ShipmentOrderStatus:
    OPEN = "OPEN"
    LOADED = "LOADED"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"
    ALL = (OPEN, LOADED, DEPARTED, CANCELLED)


# 状态机单一源头(model 层常量)。发运单 = 柜:船务生命周期单线 OPEN→LOADED→DEPARTED(+CANCELLED)。
# OPEN(组柜中)→{LOADED,CANCELLED};LOADED(已封柜)→{DEPARTED,OPEN}(撤封柜纠错口);
# DEPARTED(已发运)→{LOADED}(撤离港纠错口,清 atd);CANCELLED 终态(仅 OPEN 可达)。
# 封柜守卫(空柜 42004 / 含草稿 42003)在 service 层。
SHIPMENT_ORDER_TRANSITIONS: dict[str, set[str]] = {
    ShipmentOrderStatus.OPEN: {ShipmentOrderStatus.LOADED, ShipmentOrderStatus.CANCELLED},
    ShipmentOrderStatus.LOADED: {ShipmentOrderStatus.DEPARTED, ShipmentOrderStatus.OPEN},
    ShipmentOrderStatus.DEPARTED: {ShipmentOrderStatus.LOADED},
    ShipmentOrderStatus.CANCELLED: set(),
}

# 字段组(仅本模块内叙述,不落第二份常量;权威源 = 下方 SHIPMENT_EDITABLE_FIELDS_BY_STATUS)。
_CONTAINER_FIELDS = frozenset({"container_no", "container_type", "seal_no"})
_SHIPPING_FIELDS = frozenset({
    "booking_no", "vessel_name", "voyage_no", "bl_no",
    "etd", "eta", "port_of_loading", "port_of_discharge",
})

# 编辑门禁单一源头(model 层常量):status → 该状态下可编辑的字段集(diff 式门禁,
# service save 逐字段比对:提交值≠库中值 且 字段∉本集 → 42005)。
# OPEN:柜物理组 + 船务组 + note(组柜期全开)。
# LOADED:船务组 + note(封柜后柜物理组锁死,船期变动是现实故船务组仍可改)。
# DEPARTED:{bl_no,eta,note}(提单离港后签发、到港预计与备注可补;其余锁死)。
# CANCELLED:空(已取消柜不可编辑)。
SHIPMENT_EDITABLE_FIELDS_BY_STATUS: dict[str, frozenset[str]] = {
    ShipmentOrderStatus.OPEN: _CONTAINER_FIELDS | _SHIPPING_FIELDS | frozenset({"note"}),
    ShipmentOrderStatus.LOADED: _SHIPPING_FIELDS | frozenset({"note"}),
    ShipmentOrderStatus.DEPARTED: frozenset({"bl_no", "eta", "note"}),
    ShipmentOrderStatus.CANCELLED: frozenset(),
}


class ShipmentOrder(Base, TimestampUpdateMixin):
    """发运单(=柜)。组柜容器 + 船务生命周期(封柜/离港)。船务字段全 nullable,逐步补录;
    无红线字段(成本/供应商/售价);发运不碰库存/应收(扣库存+建应收在出库确认)。"""
    __tablename__ = "shipment_orders"
    __table_args__ = (
        # 状态 DB 兜底,bound 到状态机全集(单一源头 ShipmentOrderStatus.ALL)。
        CheckConstraint(
            "status IN ('OPEN','LOADED','DEPARTED','CANCELLED')", name="ck_shporders_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # 柜号:组柜期可空,OPEN 期可改(封柜后锁死)。柜型 code(20GP/40GP/40HQ/45HQ)= 应用层
    # 枚举 + 前端镜像,不落 CHECK(受控值域框架:消费者仅表单校验)。
    container_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    container_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    seal_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 船务字段(§D5,全 nullable 逐步补录)。港口自由文本(受控值域框架:唯一消费者=展示,
    # 无按港聚合/对接需求;消费者出现再升级 UN/LOCODE 参照表)。
    booking_no: Mapped[str | None] = mapped_column(String(30), nullable=True)
    vessel_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    voyage_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bl_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    port_of_loading: Mapped[str | None] = mapped_column(String(60), nullable=True)
    port_of_discharge: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # 时间字段(§D4,独立列,预计+实际成对)。etd 预计离港 / atd 实际离港(离港确认必填录入,
    # 撤离港清)/ eta 预计到港(信息性,与 etd 同时录)。不收 ata(实际到港归物流步)。
    etd: Mapped[date | None] = mapped_column(Date, nullable=True)
    eta: Mapped[date | None] = mapped_column(Date, nullable=True)
    atd: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 封柜确认置、撤封柜清(镜像出库 issued_at:详情时间线消费者;离港不另立 departed_at,
    # atd 即离港业务日,动作系统时刻走 audit_logs,无双源头)。
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 列表状态过滤路径。index=True 走默认命名(ix_shipment_orders_status),与迁移 0025 同名。
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ShipmentOrderStatus.OPEN, index=True)
    # 建单人(审计归属);状态动作走 audit_logs,不加 loaded_by/updated_by(遵审计归属判据)。
    created_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
