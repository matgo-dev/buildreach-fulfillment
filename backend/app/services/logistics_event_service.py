"""物流轨迹事件服务(发运柜子资源)。货离港后在途里程碑(中转/到港)手动录入。

锁序(TOCTOU 闭合):录/改/作废事件一律先锁柜头 FOR UPDATE(复用 get_order_for_update)再校验
DEPARTED——与「undepart 前置无活动事件」串行化,杜绝并发下「LOADED 柜带事件」。事件表是柜的
下游,锁柜头后只碰事件行,不破坏既有「柜头恒为叶子锁」。无红线字段。

「当前物流状态」纯派生(取 event_at 最新活动事件),发运柜上不落 current_status 冗余列。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.exceptions import (
    NotFoundError,
    ShipmentEventDuplicateArrivedError,
    ShipmentEventNotOnShipmentError,
    ShipmentNotDepartedError,
    ValidationFailedError,
)
from app.db.models.shipment_event import LogisticsMilestone, ShipmentEvent
from app.db.models.shipment_order import ShipmentOrder, ShipmentOrderStatus
from app.services import shipment_service


async def _lock_departed_shipment(db: AsyncSession, shipment_id: int) -> ShipmentOrder:
    """锁柜头(FOR UPDATE)+ 校验 DEPARTED。录/改/作废事件的统一前置,串行化并发。"""
    ship = await shipment_service.get_order_for_update(db, shipment_id)
    if ship.status != ShipmentOrderStatus.DEPARTED:
        raise ShipmentNotDepartedError()
    return ship


async def _get_active_event(db: AsyncSession, shipment_id: int, event_id: int) -> ShipmentEvent:
    """取活动事件(deleted_at IS NULL);不存在 → 404;存在但不属于该柜 → 42010(镜像 41903)。"""
    ev = (await db.execute(
        select(ShipmentEvent).where(
            ShipmentEvent.id == event_id, ShipmentEvent.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if ev is None:
        raise NotFoundError(f"物流事件不存在: {event_id}")
    if ev.shipment_id != shipment_id:
        raise ShipmentEventNotOnShipmentError()
    return ev


async def _has_active_arrived(db: AsyncSession, shipment_id: int, *, exclude_id: int | None = None) -> bool:
    """该柜是否已有活动 ARRIVED(service 主动查给友好 42009;DB 偏唯一兜底并发漏网)。
    no_autoflush:update 场景 ev.event_type 已改为 ARRIVED 但未落库,若此查触发 autoflush
    会先撞偏唯一抛 IntegrityError(500),故显式关自动 flush,只读已落库行。"""
    conds = [
        ShipmentEvent.shipment_id == shipment_id,
        ShipmentEvent.event_type == LogisticsMilestone.ARRIVED,
        ShipmentEvent.deleted_at.is_(None),
    ]
    if exclude_id is not None:
        conds.append(ShipmentEvent.id != exclude_id)
    with db.no_autoflush:
        return (await db.execute(select(func.count(ShipmentEvent.id)).where(*conds))).scalar_one() > 0


def _assert_event_at_ge_atd(event_at: date, atd: date | None) -> None:
    """事件业务日不得早于离港日(零成本防明显脏数据;拒 400)。atd 恒非空(DEPARTED 前置)。"""
    if atd is not None and event_at < atd:
        raise ValidationFailedError("物流事件日期不得早于离港日")


async def _assert_arrived_is_terminal(db: AsyncSession, shipment_id: int, *, event_type: str,
                                      event_at: date, exclude_id: int | None = None) -> None:
    """到港=时间线终点(写入口守卫,拒 400):
    - 录/改非到港事件:日期不得晚于该柜活动到港日(到港后不再有在途节点);
    - 录/改到港事件:日期不得早于该柜其它活动事件的最大日期。
    与派生口径「活动到港=终态」同一规则的写侧表达。no_autoflush 同 _has_active_arrived。"""
    conds = [ShipmentEvent.shipment_id == shipment_id, ShipmentEvent.deleted_at.is_(None)]
    if exclude_id is not None:
        conds.append(ShipmentEvent.id != exclude_id)
    if event_type == LogisticsMilestone.ARRIVED:
        with db.no_autoflush:
            max_other = (await db.execute(
                select(func.max(ShipmentEvent.event_at)).where(*conds))).scalar_one()
        if max_other is not None and event_at < max_other:
            raise ValidationFailedError("到港日期不得早于已录的在途事件")
    else:
        with db.no_autoflush:
            arrived_at = (await db.execute(
                select(ShipmentEvent.event_at).where(
                    *conds, ShipmentEvent.event_type == LogisticsMilestone.ARRIVED))
            ).scalar_one_or_none()
        if arrived_at is not None and event_at > arrived_at:
            raise ValidationFailedError("事件日期不得晚于到港日")


async def create_event(db: AsyncSession, *, shipment_id: int, event_type: str, event_at: date,
                       location: str | None, note: str | None, actor_user_id, actor_user_email,
                       request: Request | None = None) -> ShipmentEvent:
    """录入里程碑。管线:锁柜头 → DEPARTED → event_at≥atd → 到港唯一 → 到港终点 → 建。"""
    ship = await _lock_departed_shipment(db, shipment_id)
    _assert_event_at_ge_atd(event_at, ship.atd)
    if event_type == LogisticsMilestone.ARRIVED and await _has_active_arrived(db, shipment_id):
        raise ShipmentEventDuplicateArrivedError()
    await _assert_arrived_is_terminal(db, shipment_id, event_type=event_type, event_at=event_at)
    ev = ShipmentEvent(shipment_id=shipment_id, event_type=event_type, event_at=event_at,
                       location=location, note=note, created_by=actor_user_id)
    db.add(ev)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_EVENT,
                      action=AuditAction.CREATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ev.id, request=request,
                      extra={"shipment_id": shipment_id}, commit=False)
    await db.commit()
    await db.refresh(ev)
    return ev


async def update_event(db: AsyncSession, *, shipment_id: int, event_id: int, fields: dict,
                       actor_user_id, actor_user_email,
                       request: Request | None = None) -> ShipmentEvent:
    """纠错改事件(稀疏:仅传入字段覆盖)。管线:锁柜头 → DEPARTED → 取活动事件+归属 →
    覆盖 → 到港唯一(排除自身)→ event_at≥atd → 到港终点(排除自身)。
    event_type/event_at 显式传 None 视为非法(NOT NULL)。"""
    ship = await _lock_departed_shipment(db, shipment_id)
    ev = await _get_active_event(db, shipment_id, event_id)
    for name in ("event_type", "event_at", "location", "note"):
        if name in fields:
            if name in ("event_type", "event_at") and fields[name] is None:
                raise ValidationFailedError(f"{name} 不可置空")
            setattr(ev, name, fields[name])
    if ev.event_type == LogisticsMilestone.ARRIVED and await _has_active_arrived(
            db, shipment_id, exclude_id=ev.id):
        raise ShipmentEventDuplicateArrivedError()
    _assert_event_at_ge_atd(ev.event_at, ship.atd)
    await _assert_arrived_is_terminal(db, shipment_id, event_type=ev.event_type,
                                      event_at=ev.event_at, exclude_id=ev.id)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_EVENT,
                      action=AuditAction.UPDATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ev.id, request=request,
                      extra={"shipment_id": shipment_id}, commit=False)
    await db.commit()
    await db.refresh(ev)
    return ev


async def delete_event(db: AsyncSession, *, shipment_id: int, event_id: int, actor_user_id,
                       actor_user_email, request: Request | None = None) -> None:
    """作废物流节点(底层置 deleted_at)。管线:锁柜头 → DEPARTED → 取活动事件+归属 → 作废。
    作废后行保留供追溯,且退出到港偏唯一(旧到港作废后可重录);extra 带整行快照。"""
    await _lock_departed_shipment(db, shipment_id)
    ev = await _get_active_event(db, shipment_id, event_id)
    snapshot = {"event_type": ev.event_type, "event_at": ev.event_at.isoformat(),
                "location": ev.location, "note": ev.note}
    # deleted_at 是 tz-aware DateTime(timezone=True)(SoftDeleteMixin),对齐 sku/spu 软删写法。
    ev.deleted_at = datetime.now(timezone.utc)
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_EVENT,
                      action=AuditAction.DELETE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ev.id, request=request,
                      extra={"shipment_id": shipment_id, "snapshot": snapshot}, commit=False)
    await db.commit()


# ---------- 轨迹查询 + 当前物流状态派生(纯派生,零冗余列)----------


def derive_current_status(ship_status: str, latest_event_type: str | None) -> str | None:
    """当前物流状态(唯一口径):非 DEPARTED → None(列表显「—」);DEPARTED 无活动事件 →
    已离港 DEPARTED;有活动事件 → 最新事件 event_type。"""
    if ship_status != ShipmentOrderStatus.DEPARTED:
        return None
    return latest_event_type or LogisticsMilestone.DEPARTED


def latest_event_select():
    """每柜「最新」活动事件 `(shipment_id, event_type)` 的 DISTINCT ON select —— **口径单一源头**。
    列表派生列(latest_event_types)/ 物流状态筛选(shipment_service.list_orders)全复用此构造,
    不各写一份 DISTINCT ON。排序 = 活动到港终态优先,再 event_at DESC, id DESC(event_at 是
    Date,同日靠 id 定序)。写侧守卫(_assert_arrived_is_terminal)保证到港日恒为最大,
    终态优先仅在「同日并列」时生效,与 latest_type_of 同口径。"""
    return (
        select(ShipmentEvent.shipment_id, ShipmentEvent.event_type)
        .distinct(ShipmentEvent.shipment_id)
        .where(ShipmentEvent.deleted_at.is_(None))
        .order_by(ShipmentEvent.shipment_id,
                  (ShipmentEvent.event_type == LogisticsMilestone.ARRIVED).desc(),
                  ShipmentEvent.event_at.desc(), ShipmentEvent.id.desc())
    )


def latest_type_of(events: list[ShipmentEvent]) -> str | None:
    """从某柜活动事件列表(list_events 正序)取派生口径的「最新」事件类型 —— 详情路径复用已取
    的 events,免二次查询。规则与 latest_event_select 同口径:活动到港=终态(每柜至多一条),
    否则末位 =(event_at, id)最大。"""
    if not events:
        return None
    arrived = next((ev for ev in events if ev.event_type == LogisticsMilestone.ARRIVED), None)
    return arrived.event_type if arrived is not None else events[-1].event_type


async def latest_event_types(db: AsyncSession, shipment_ids: list[int]) -> dict[int, str]:
    """批量:各柜最新活动事件的 event_type(列表派生列,单条批量走复合索引,无 N+1)。"""
    if not shipment_ids:
        return {}
    rows = (await db.execute(
        latest_event_select().where(ShipmentEvent.shipment_id.in_(shipment_ids)))).all()
    return {sid: et for sid, et in rows}


async def list_events(db: AsyncSession, shipment_id: int) -> list[ShipmentEvent]:
    """某柜活动事件正序(时间线;event_at ASC, id ASC)。详情内联轨迹。"""
    return list((await db.execute(
        select(ShipmentEvent)
        .where(ShipmentEvent.shipment_id == shipment_id, ShipmentEvent.deleted_at.is_(None))
        .order_by(ShipmentEvent.event_at.asc(), ShipmentEvent.id.asc()))).scalars().all())
