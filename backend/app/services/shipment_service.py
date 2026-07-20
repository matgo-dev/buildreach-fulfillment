"""发运单(=柜)服务:组柜容器 + 船务生命周期(装柜/离港)。
建 / 改(diff 式字段门禁 + 乐观锁)/ 取消 / 装柜确认 / 撤装柜 / 离港确认 / 撤离港。

发运不碰库存、不碰应收(扣库存 + 建应收都在出库确认);柜只管船务生命周期。无红线字段。

取消守卫:柜下存在非 CANCELLED 出库单 → 拒(42001)。先取消柜内出库单再取消柜。
锁序:柜头恒为叶子锁——load/unload/depart/undepart 只锁柜头(FOR UPDATE)后读出库聚合
(只读不加锁),不向下要锁;出库侧 create/confirm/revert 均「SO 头 → 出库单头 → 柜头」。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    NotFoundError,
    ShipmentEditConflictError,
    ShipmentEmptyCannotLoadError,
    ShipmentFieldNotEditableError,
    ShipmentHasActiveOutboundError,
    ShipmentHasDraftOutboundError,
    ShipmentInvalidTransitionError,
)
from app.core.statemachine import assert_transition
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.shipment_order import (
    SHIPMENT_EDITABLE_FIELDS_BY_STATUS,
    SHIPMENT_ORDER_TRANSITIONS,
    ShipmentOrder,
    ShipmentOrderStatus,
)
from app.services.numbering import allocate
from app.services.repo import assert_no_edit_conflict, get_or_404, paginate

# 整单保存可写字段(全量覆盖式;门禁由 SHIPMENT_EDITABLE_FIELDS_BY_STATUS 逐字段 diff)。
# atd 不在此——由离港确认动作驱动,不走整单保存。
_SAVE_FIELDS = (
    "container_no", "container_type", "seal_no", "note",
    "booking_no", "vessel_name", "voyage_no", "bl_no",
    "port_of_loading", "port_of_discharge", "etd", "eta",
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _assert_edge(ship: ShipmentOrder, source: str, target: str) -> None:
    """命名动作 = 状态机的一条特定边(source→target)。守卫必须锚定**源态**:
    仅校验 target∈matrix[current] 不够——load(OPEN→LOADED)与 undepart(DEPARTED→LOADED)
    同目标,只查目标会让 undepart 在 OPEN 柜上误通过。current≠源态 → 非法转移(单义 42002)。
    边本身须在矩阵内(契约不变量,防手误加错动作;显式 raise 不用 assert——-O 下不可剥)。"""
    if target not in SHIPMENT_ORDER_TRANSITIONS[source]:
        raise RuntimeError(f"动作未对应状态机合法边: {source} → {target}")
    if ship.status != source:
        raise ShipmentInvalidTransitionError(f"非法转移: {ship.status} → {target}")


async def _next_shipment_no(db: AsyncSession) -> str:
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.SHIPMENT, period)
    return format_code(NumberScope.SHIPMENT, seq, period)


async def get_order(db: AsyncSession, shipment_id: int) -> ShipmentOrder:
    return await get_or_404(db, ShipmentOrder, shipment_id,
                            error_cls=NotFoundError, message=f"柜不存在: {shipment_id}")


async def get_order_for_update(db: AsyncSession, shipment_id: int) -> ShipmentOrder:
    return await get_or_404(db, ShipmentOrder, shipment_id, for_update=True,
                            error_cls=NotFoundError, message=f"柜不存在: {shipment_id}")


async def create_order(db: AsyncSession, *, fields: dict, actor_user_id, actor_user_email,
                       request: Request | None = None) -> ShipmentOrder:
    """建柜(OPEN)。fields 含柜物理组 + 船务组(全可选,建柜即录)。"""
    ship = ShipmentOrder(
        no=await _next_shipment_no(db), status=ShipmentOrderStatus.OPEN,
        created_by=actor_user_id,
        **{k: fields.get(k) for k in _SAVE_FIELDS})
    db.add(ship)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.CREATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


async def save_order(db: AsyncSession, *, shipment_id, fields: dict, expected_updated_at,
                     actor_user_id, actor_user_email,
                     request: Request | None = None) -> ShipmentOrder:
    """改柜(稀疏 PATCH + 乐观锁 + diff 式字段门禁)。
    stale 提交 → 42006(编辑冲突);提交值≠库中值 且 字段∉当前状态可编辑集 → 42005
    (biz_data 带被拒字段名);值未变的字段即使不可编辑也放行。
    **仅处理客户端显式提交的字段**(fields = exclude_unset 结果):未传字段既不 diff
    也不覆盖——局部 PATCH 不会误清空其它字段、不会拿未传字段的 None 误报 42005。"""
    ship = await get_order_for_update(db, shipment_id)
    assert_no_edit_conflict(ship, expected_updated_at, ShipmentEditConflictError)
    editable = SHIPMENT_EDITABLE_FIELDS_BY_STATUS[ship.status]
    provided = [name for name in _SAVE_FIELDS if name in fields]
    forbidden = [name for name in provided
                 if fields[name] != getattr(ship, name) and name not in editable]
    if forbidden:
        raise ShipmentFieldNotEditableError(data={"fields": forbidden})
    for name in provided:
        setattr(ship, name, fields[name])
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.UPDATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


async def cancel_order(db: AsyncSession, *, shipment_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> ShipmentOrder:
    """取消柜(仅 OPEN→CANCELLED)。守卫:柜下有非 CANCELLED 出库单 → 42001。"""
    ship = await get_order_for_update(db, shipment_id)
    assert_transition(SHIPMENT_ORDER_TRANSITIONS, ship.status, ShipmentOrderStatus.CANCELLED,
                      ShipmentInvalidTransitionError)
    active = (await db.execute(
        select(func.count(OutboundOrder.id)).where(
            OutboundOrder.shipment_id == shipment_id,
            OutboundOrder.status != OutboundOrderStatus.CANCELLED))).scalar_one()
    if active > 0:
        raise ShipmentHasActiveOutboundError()
    ship.status = ShipmentOrderStatus.CANCELLED
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.CANCEL, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


# ---------- 船务状态机(叶子锁:只锁柜头,读出库聚合不加锁)----------


async def load_order(db: AsyncSession, *, shipment_id, container_no=None, seal_no=None,
                     actor_user_id, actor_user_email,
                     request: Request | None = None) -> ShipmentOrder:
    """装柜确认(OPEN→LOADED)。守卫:柜内 ≥1 非 CANCELLED 出库单(空柜 42004),
    且全部为 ISSUED(存在 DRAFT → 42003 带草稿单号列表)。置 loaded_at;可带 seal_no/
    container_no 补录(封条贴上才知)。柜头 FOR UPDATE(叶子锁),出库聚合只读不加锁。"""
    ship = await get_order_for_update(db, shipment_id)
    _assert_edge(ship, ShipmentOrderStatus.OPEN, ShipmentOrderStatus.LOADED)
    rows = (await db.execute(
        select(OutboundOrder.no, OutboundOrder.status).where(
            OutboundOrder.shipment_id == shipment_id,
            OutboundOrder.status != OutboundOrderStatus.CANCELLED))).all()
    if not rows:
        raise ShipmentEmptyCannotLoadError()
    draft_nos = [no for no, st in rows if st == OutboundOrderStatus.DRAFT]
    if draft_nos:
        raise ShipmentHasDraftOutboundError(data={"draft_nos": draft_nos})
    if container_no is not None:
        ship.container_no = container_no
    if seal_no is not None:
        ship.seal_no = seal_no
    ship.status = ShipmentOrderStatus.LOADED
    ship.loaded_at = _now()
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.LOAD, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


async def unload_order(db: AsyncSession, *, shipment_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> ShipmentOrder:
    """撤装柜(LOADED→OPEN,纠错口)。清 loaded_at;柜内出库单随之解冻(可撤/可改)。"""
    ship = await get_order_for_update(db, shipment_id)
    _assert_edge(ship, ShipmentOrderStatus.LOADED, ShipmentOrderStatus.OPEN)
    ship.status = ShipmentOrderStatus.OPEN
    ship.loaded_at = None
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.UNLOAD, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


async def depart_order(db: AsyncSession, *, shipment_id, atd: date, actor_user_id,
                       actor_user_email, request: Request | None = None) -> ShipmentOrder:
    """离港确认(LOADED→DEPARTED)。atd 实际离港日,**必填**(schema 422 兜底)——
    业务日期须由操作者按本地时区给出,服务端 UTC 猜「当日」在东八区 0-8 点必错一天;
    「默认今天」的便利活在前端 DatePicker,不落服务端。extra 记 atd。"""
    ship = await get_order_for_update(db, shipment_id)
    _assert_edge(ship, ShipmentOrderStatus.LOADED, ShipmentOrderStatus.DEPARTED)
    ship.status = ShipmentOrderStatus.DEPARTED
    ship.atd = atd
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.DEPART, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      extra={"atd": atd.isoformat()}, commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


async def undepart_order(db: AsyncSession, *, shipment_id, actor_user_id, actor_user_email,
                         request: Request | None = None) -> ShipmentOrder:
    """撤离港(DEPARTED→LOADED,误点纠错)。清 atd;extra 记被清的 atd。"""
    ship = await get_order_for_update(db, shipment_id)
    _assert_edge(ship, ShipmentOrderStatus.DEPARTED, ShipmentOrderStatus.LOADED)
    cleared_atd = ship.atd
    ship.status = ShipmentOrderStatus.LOADED
    ship.atd = None
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.UNDEPART, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      extra={"atd": cleared_atd.isoformat()} if cleared_atd else None,
                      commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


# ---------- 柜内出库单计数 / 列表 ----------


async def _outbound_counts(db: AsyncSession, shipment_ids: list[int]) -> dict[int, int]:
    """批量:各柜下非 CANCELLED 出库单数(列表徽标 + 详情组柜台)。"""
    if not shipment_ids:
        return {}
    rows = (await db.execute(
        select(OutboundOrder.shipment_id, func.count(OutboundOrder.id))
        .where(OutboundOrder.shipment_id.in_(shipment_ids),
               OutboundOrder.status != OutboundOrderStatus.CANCELLED)
        .group_by(OutboundOrder.shipment_id))).all()
    return {sid: cnt for sid, cnt in rows}


async def outbound_count(db: AsyncSession, shipment_id: int) -> int:
    return (await _outbound_counts(db, [shipment_id])).get(shipment_id, 0)


async def list_orders(db: AsyncSession, *, status=None, keyword=None, page: int = 1,
                      size: int = 20) -> tuple[list[dict], int]:
    """柜列表:状态过滤 + 关键字(柜号 / 柜单号)+ 分页,created_at 降序。
    投影柜内出库单数 + 船务概览列(船名/航次/ETD/ATD)。"""
    conds = []
    if status:
        conds.append(ShipmentOrder.status == status)
    if keyword:
        like = f"%{keyword}%"
        conds.append(ShipmentOrder.no.ilike(like) | ShipmentOrder.container_no.ilike(like))
    rows, total = await paginate(
        db, select(ShipmentOrder).where(*conds).order_by(ShipmentOrder.created_at.desc()),
        page=page, size=size)
    counts = await _outbound_counts(db, [s.id for s in rows])
    items = [{
        "id": s.id, "no": s.no, "container_no": s.container_no,
        "container_type": s.container_type, "seal_no": s.seal_no,
        "vessel_name": s.vessel_name, "voyage_no": s.voyage_no, "etd": s.etd, "atd": s.atd,
        "status": s.status, "outbound_count": counts.get(s.id, 0), "created_at": s.created_at,
    } for s in rows]
    return items, total
