"""发运单(=柜)服务:组柜容器 + 船务生命周期(封柜/离港)。
建 / 改(diff 式字段门禁 + 乐观锁)/ 取消 / 封柜确认 / 撤封柜 / 离港确认 / 撤离港。

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
    ShipmentHasActiveCustomsError,
    ShipmentHasActiveLogisticsEventError,
    ShipmentHasActiveOutboundError,
    ShipmentHasDraftOutboundError,
    ShipmentInvalidTransitionError,
)
from app.core.statemachine import assert_transition
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.customs_declaration import CustomsDeclaration
from app.db.models.shipment_event import LogisticsMilestone, ShipmentEvent
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


async def load_order(db: AsyncSession, *, shipment_id, expected_updated_at,
                     container_no=None, seal_no=None, actor_user_id, actor_user_email,
                     request: Request | None = None) -> ShipmentOrder:
    """封柜确认(OPEN→LOADED)。检查管线 = 锁 → 乐观锁基线 → 状态机边 → 业务守卫
    (与 save_order 同序):stale 提交 → 42006(补录会覆盖柜号/封条,须持最新基线);
    柜内 ≥1 非 CANCELLED 出库单(空柜 42004)且全部 ISSUED(存在 DRAFT → 42003 带草稿
    单号列表)。置 loaded_at;补录覆盖旧值记审计 extra。柜头 FOR UPDATE(叶子锁),
    出库聚合只读不加锁。"""
    ship = await get_order_for_update(db, shipment_id)
    assert_no_edit_conflict(ship, expected_updated_at, ShipmentEditConflictError)
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
    # 补录覆盖旧值 → extra 留痕(排障:谁在封柜时改了柜号/封条、改前是什么)。
    extra: dict = {}
    if container_no is not None and container_no != ship.container_no:
        extra["container_no"] = {"old": ship.container_no, "new": container_no}
        ship.container_no = container_no
    if seal_no is not None and seal_no != ship.seal_no:
        extra["seal_no"] = {"old": ship.seal_no, "new": seal_no}
        ship.seal_no = seal_no
    ship.status = ShipmentOrderStatus.LOADED
    ship.loaded_at = _now()
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.LOAD, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      extra=extra or None, commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


async def unload_order(db: AsyncSession, *, shipment_id, actor_user_id, actor_user_email,
                       request: Request | None = None) -> ShipmentOrder:
    """撤封柜(LOADED→OPEN,纠错口)。清 loaded_at;柜内出库单随之解冻(可撤/可改)。
    守卫:柜下存在活动报关记录 → 拒 42011(柜内容变了申报即失效,须先删报关再撤封柜;
    同 42007 撤离港被活动物流事件拦的范式)。锁柜头后查,与「录报关前置柜态」串行化。"""
    ship = await get_order_for_update(db, shipment_id)
    _assert_edge(ship, ShipmentOrderStatus.LOADED, ShipmentOrderStatus.OPEN)
    active_customs = (await db.execute(
        select(func.count(CustomsDeclaration.id)).where(
            CustomsDeclaration.shipment_order_id == shipment_id,
            CustomsDeclaration.deleted_at.is_(None)))).scalar_one()
    if active_customs > 0:
        raise ShipmentHasActiveCustomsError()
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
    """撤离港(DEPARTED→LOADED,误点纠错)。清 atd;extra 记被清的 atd。
    守卫:柜下存在活动物流事件(deleted_at IS NULL)→ 拒 42007(离港是物流轨迹起点,
    撤离港清 atd,须先软删事件再撤)。锁柜头后查,与「录事件前置 DEPARTED」串行化(TOCTOU 闭合)。"""
    ship = await get_order_for_update(db, shipment_id)
    _assert_edge(ship, ShipmentOrderStatus.DEPARTED, ShipmentOrderStatus.LOADED)
    active_events = (await db.execute(
        select(func.count(ShipmentEvent.id)).where(
            ShipmentEvent.shipment_id == shipment_id,
            ShipmentEvent.deleted_at.is_(None)))).scalar_one()
    if active_events > 0:
        raise ShipmentHasActiveLogisticsEventError()
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


async def list_orders(db: AsyncSession, *, status=None, keyword=None, logistics_status=None,
                      customs_status=None, page: int = 1, size: int = 20
                      ) -> tuple[list[dict], int]:
    """柜列表:状态过滤 + 物流状态过滤(派生)+ 报关状态过滤(派生)+ 关键字(柜号 / 柜单号)+
    分页,created_at 降序。投影柜内出库单数 + 船务概览列 + 当前物流状态 + 报关状态派生列。"""
    stmt = select(ShipmentOrder)
    conds = []
    if status:
        conds.append(ShipmentOrder.status == status)
    if keyword:
        like = f"%{keyword}%"
        conds.append(ShipmentOrder.no.ilike(like) | ShipmentOrder.container_no.ilike(like))
    if customs_status:
        # 报关状态纯派生 → LEFT JOIN 活动报关记录(偏唯一保证每柜至多一行,无放大)。
        # NONE=柜 LOADED/DEPARTED 且无活动报关;DECLARED=有活动且未回填放行;RELEASED=已回填。
        from app.db.models.customs_declaration import CustomsDeclaration, CustomsStatus
        active_cd = (
            select(CustomsDeclaration.shipment_order_id.label("sid"),
                   CustomsDeclaration.released_at.label("released_at"))
            .where(CustomsDeclaration.deleted_at.is_(None)).subquery())
        stmt = stmt.outerjoin(active_cd, active_cd.c.sid == ShipmentOrder.id)
        if customs_status == CustomsStatus.NONE:
            conds.append(ShipmentOrder.status.in_(
                [ShipmentOrderStatus.LOADED, ShipmentOrderStatus.DEPARTED]))
            conds.append(active_cd.c.sid.is_(None))
        elif customs_status == CustomsStatus.DECLARED:
            conds.append(active_cd.c.sid.isnot(None))
            conds.append(active_cd.c.released_at.is_(None))
        elif customs_status == CustomsStatus.RELEASED:
            conds.append(active_cd.c.released_at.isnot(None))
    if logistics_status:
        # 物流状态纯派生 → 按「每柜最新活动事件」LEFT JOIN 过滤。复用 logistics_event_service
        # 的 latest_event_select()(DISTINCT ON 口径单一源头,不再手写第二份;函数内 import
        # 破 service 互引循环)。发运柜有界小表(月十位数级),派生筛选走 (shipment_id, event_at)
        # 索引、latest 每柜≤1 行不放大,非增长型性能雷(区别于大数据量的库存可发量派生)。
        from app.services import logistics_event_service
        latest = logistics_event_service.latest_event_select().subquery()
        stmt = stmt.outerjoin(latest, latest.c.shipment_id == ShipmentOrder.id)
        # 物流状态非空 ⟺ 柜 DEPARTED —— 此 WHERE 三分支与 derive_current_status 单行派生同口径
        # (集合筛选 vs 单行,两种表达一处规则):已离港=DEPARTED 且无活动事件;中转/到港=最新事件为该类型。
        conds.append(ShipmentOrder.status == ShipmentOrderStatus.DEPARTED)
        if logistics_status == LogisticsMilestone.DEPARTED:
            conds.append(latest.c.event_type.is_(None))
        else:
            conds.append(latest.c.event_type == logistics_status)
    rows, total = await paginate(
        db, stmt.where(*conds).order_by(ShipmentOrder.created_at.desc()),
        page=page, size=size)
    counts = await _outbound_counts(db, [s.id for s in rows])
    items = [{
        "id": s.id, "no": s.no, "container_no": s.container_no,
        "container_type": s.container_type, "seal_no": s.seal_no,
        "vessel_name": s.vessel_name, "voyage_no": s.voyage_no, "etd": s.etd, "atd": s.atd,
        "status": s.status, "outbound_count": counts.get(s.id, 0), "created_at": s.created_at,
    } for s in rows]
    return items, total
