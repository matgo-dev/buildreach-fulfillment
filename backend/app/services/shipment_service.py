"""发运单(=柜)服务:本步最小骨架(组柜容器)。建 / 改(OPEN 期柜号/柜型/封条)/ 取消。
订舱/船名航次/港/提单/报关等船务字段与装船状态机归发运步扩展。无红线字段(成本/供应商/售价)。

取消守卫:柜下存在非 CANCELLED 出库单 → 拒(42001)。先取消柜内出库单再取消柜。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import NotFoundError, ShipmentHasActiveOutboundError, \
    ShipmentInvalidTransitionError
from app.core.statemachine import assert_transition
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.shipment_order import (
    SHIPMENT_ORDER_EDITABLE_STATUSES,
    SHIPMENT_ORDER_TRANSITIONS,
    ShipmentOrder,
    ShipmentOrderStatus,
)
from app.services.numbering import allocate
from app.services.repo import get_or_404, paginate


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


async def create_order(db: AsyncSession, *, container_no, container_type, seal_no, note,
                       actor_user_id, actor_user_email,
                       request: Request | None = None) -> ShipmentOrder:
    ship = ShipmentOrder(
        no=await _next_shipment_no(db), container_no=container_no,
        container_type=container_type, seal_no=seal_no, note=note,
        status=ShipmentOrderStatus.OPEN, created_by=actor_user_id)
    db.add(ship)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SHIPMENT_ORDER,
                      action=AuditAction.CREATE, user_id=actor_user_id,
                      user_email=actor_user_email, resource_id=ship.id, request=request,
                      commit=False)
    await db.commit()
    await db.refresh(ship)
    return ship


async def save_order(db: AsyncSession, *, shipment_id, container_no, container_type, seal_no,
                     note, actor_user_id, actor_user_email,
                     request: Request | None = None) -> ShipmentOrder:
    """改柜(仅 OPEN):柜号/柜型/封条/备注。非 OPEN → 42002(状态机不允许改已取消柜)。"""
    ship = await get_order_for_update(db, shipment_id)
    if ship.status not in SHIPMENT_ORDER_EDITABLE_STATUSES:
        raise ShipmentInvalidTransitionError(f"仅组柜中(OPEN)可编辑,当前 {ship.status}")
    ship.container_no, ship.container_type = container_no, container_type
    ship.seal_no, ship.note = seal_no, note
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
    """取消柜(OPEN→CANCELLED)。守卫:柜下有非 CANCELLED 出库单 → 42001。"""
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
    """柜列表:状态过滤 + 关键字(柜号 / 柜单号)+ 分页,created_at 降序。投影柜内出库单数。"""
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
        "container_type": s.container_type, "seal_no": s.seal_no, "status": s.status,
        "outbound_count": counts.get(s.id, 0), "created_at": s.created_at,
    } for s in rows]
    return items, total
