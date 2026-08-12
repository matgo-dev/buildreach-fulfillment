"""发运单(=柜)路由 /api/v1/shipments。组柜容器 + 船务生命周期(封柜/离港)。

守 shipment:manage(写)/ shipment:read(读)。柜无红线字段(成本/供应商/售价)。
详情内嵌柜内出库单列表(组柜工作台数据),仅数量/状态,无金额。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.common import Page, PageParams
from app.schemas.shipment import (
    ShipmentCreateIn,
    ShipmentDepartIn,
    ShipmentListItem,
    ShipmentLoadIn,
    ShipmentOut,
    ShipmentUpdateIn,
)
from app.schemas.shipment_event import (
    ShipmentEventCreateIn,
    ShipmentEventOut,
    ShipmentEventUpdateIn,
)
from app.schemas.customs import (
    CustomsDeclarationCreateIn,
    CustomsDeclarationOut,
    CustomsDeclarationUpdateIn,
)
from app.services import (
    attachment_service,
    customs_service,
    logistics_event_service,
    outbound_service,
    shipment_service,
)

router = APIRouter(prefix="/shipments", tags=["shipments"])

_READ = Depends(require_any_permission(Permissions.SHIPMENT_READ, Permissions.SHIPMENT_MANAGE))
_MANAGE = Depends(require_permission(Permissions.SHIPMENT_MANAGE))


async def _detail_payload(db, ship) -> dict:
    outbounds = await outbound_service.list_orders(db, shipment_id=ship.id, size=200)
    count = await shipment_service.outbound_count(db, ship.id)
    # 物流轨迹(活动事件正序);当前物流状态纯派生自最新事件,不查冗余列。latest_type_of 复用
    # 已取的 events(活动到港=终态优先,与 latest_event_select 同口径),不再另查 latest_event_types。
    events = await logistics_event_service.list_events(db, ship.id)
    latest_type = logistics_event_service.latest_type_of(events)
    # 报关(活动一条或 null)。活动记录必属 LOADED/DEPARTED 柜(撤封柜被活动报关拦)。
    decl = await customs_service.get_active(db, ship.id)
    customs_atts = (await attachment_service.list_for_declaration(db, decl.id)
                    if decl is not None else [])
    return {
        "shipment": ShipmentOut.build(ship, {"outbound_count": count}),
        "customs_declaration": (
            CustomsDeclarationOut.build(
                decl, status=customs_service.derive_status(decl), attachments=customs_atts)
            if decl is not None else None),
        # 派生报关状态(OPEN/CANCELLED → None 显「—」;LOADED/DEPARTED → NONE/DECLARED/RELEASED)。
        # 前端据此决定是否显「录入报关」入口(NONE 且 manage 才显)。
        "customs_status": customs_service.derive_list_status(ship.status, decl),
        # 柜内出库单(组柜工作台);列=SO 号/柜/行数/件数/状态,无金额。
        "outbound_orders": [{
            "id": it["id"], "no": it["no"], "sales_order_id": it["sales_order_id"],
            "sales_order_no": it["sales_order_no"], "customer_display": it["customer_display"],
            "status": it["status"],
            "line_count": it["line_count"], "total_qty": it["total_qty"],
        } for it in outbounds[0]],
        # 全流程时间线数据:已离港节点读柜 atd(在 shipment.atd),中转/到港读事件。
        "logistics_events": [ShipmentEventOut.build(ev) for ev in events],
        "current_logistics_status": logistics_event_service.derive_current_status(
            ship.status, latest_type),
    }


@router.post("", summary="建柜(组柜中,可带船务字段)")
async def create_shipment(body: ShipmentCreateIn, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    ship = await shipment_service.create_order(
        db, fields=body.model_dump(), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, ship))


@router.get("", summary="柜列表(筛选/分页)")
async def list_shipments(page_params: PageParams = Depends(), status: str | None = None,
                         keyword: str | None = None, logistics_status: str | None = None,
                         customs_status: str | None = None,
                         _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await shipment_service.list_orders(
        db, status=status, keyword=keyword, logistics_status=logistics_status,
        customs_status=customs_status, page=page_params.page, size=page_params.size)
    ids = [it["id"] for it in items]
    # 派生当前物流状态列(批量,单条走复合索引,无 N+1);非 DEPARTED 柜派生为 None(前端显「—」)。
    latest = await logistics_event_service.latest_event_types(db, ids)
    # 派生报关状态列(批量,单条走偏唯一索引,无 N+1);OPEN/CANCELLED 柜派生为 None。
    active_customs = await customs_service.active_by_shipments(db, ids)
    for it in items:
        it["current_logistics_status"] = logistics_event_service.derive_current_status(
            it["status"], latest.get(it["id"]))
        it["customs_status"] = customs_service.derive_list_status(
            it["status"], active_customs.get(it["id"]))
    return success(Page(
        items=[ShipmentListItem.model_validate(it).model_dump() for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/{shipment_id}", summary="取柜(组柜工作台:柜信息 + 船务 + 柜内出库单)")
async def get_shipment(shipment_id: int, _current: CurrentUser = _READ,
                       db: AsyncSession = Depends(get_db)):
    ship = await shipment_service.get_order(db, shipment_id)
    return success(await _detail_payload(db, ship))


@router.patch("/{shipment_id}", summary="改柜(按状态×字段门禁 + 乐观锁)")
async def update_shipment(shipment_id: int, body: ShipmentUpdateIn, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    ship = await shipment_service.save_order(
        db, shipment_id=shipment_id,
        # 稀疏 PATCH:仅下发客户端显式提交的字段(exclude_unset),未传字段不参与门禁/覆盖。
        fields=body.model_dump(exclude_unset=True, exclude={"expected_updated_at"}),
        expected_updated_at=body.expected_updated_at, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, ship))


@router.post("/{shipment_id}/load", summary="封柜确认(OPEN→LOADED,乐观锁必填,可补录封条/柜号)")
async def load_shipment(shipment_id: int, body: ShipmentLoadIn, request: Request,
                        current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    ship = await shipment_service.load_order(
        db, shipment_id=shipment_id, expected_updated_at=body.expected_updated_at,
        container_no=body.container_no, seal_no=body.seal_no,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, ship))


@router.post("/{shipment_id}/unload", summary="撤封柜(LOADED→OPEN,清 loaded_at)")
async def unload_shipment(shipment_id: int, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    ship = await shipment_service.unload_order(
        db, shipment_id=shipment_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(await _detail_payload(db, ship))


@router.post("/{shipment_id}/depart", summary="离港确认(LOADED→DEPARTED,atd 必填)")
async def depart_shipment(shipment_id: int, body: ShipmentDepartIn, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    ship = await shipment_service.depart_order(
        db, shipment_id=shipment_id, atd=body.atd, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, ship))


@router.post("/{shipment_id}/undepart", summary="撤离港(DEPARTED→LOADED,清 atd)")
async def undepart_shipment(shipment_id: int, request: Request,
                            current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    ship = await shipment_service.undepart_order(
        db, shipment_id=shipment_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(await _detail_payload(db, ship))


@router.post("/{shipment_id}/cancel", summary="取消柜(柜下有活动出库单则拒)")
async def cancel_shipment(shipment_id: int, request: Request,
                          current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    ship = await shipment_service.cancel_order(
        db, shipment_id=shipment_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(await _detail_payload(db, ship))


# ---------- 物流轨迹事件(发运柜子资源;录/改/作废前置柜 DEPARTED,锁柜头串行化)----------


@router.post("/{shipment_id}/logistics-events", summary="录入物流里程碑(中转/到港)")
async def create_logistics_event(shipment_id: int, body: ShipmentEventCreateIn, request: Request,
                                 current: CurrentUser = _MANAGE,
                                 db: AsyncSession = Depends(get_db)):
    await logistics_event_service.create_event(
        db, shipment_id=shipment_id, event_type=body.event_type, event_at=body.event_at,
        location=body.location, note=body.note, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    ship = await shipment_service.get_order(db, shipment_id)
    return success(await _detail_payload(db, ship))


@router.patch("/{shipment_id}/logistics-events/{event_id}", summary="改物流事件(纠错)")
async def update_logistics_event(shipment_id: int, event_id: int, body: ShipmentEventUpdateIn,
                                 request: Request, current: CurrentUser = _MANAGE,
                                 db: AsyncSession = Depends(get_db)):
    await logistics_event_service.update_event(
        db, shipment_id=shipment_id, event_id=event_id,
        fields=body.model_dump(exclude_unset=True), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    ship = await shipment_service.get_order(db, shipment_id)
    return success(await _detail_payload(db, ship))


@router.delete("/{shipment_id}/logistics-events/{event_id}", summary="作废物流节点(底层软删留痕)")
async def delete_logistics_event(shipment_id: int, event_id: int, request: Request,
                                 current: CurrentUser = _MANAGE,
                                 db: AsyncSession = Depends(get_db)):
    await logistics_event_service.delete_event(
        db, shipment_id=shipment_id, event_id=event_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    ship = await shipment_service.get_order(db, shipment_id)
    return success(await _detail_payload(db, ship))


# ---------- 报关记录(发运柜子资源;整柜一次报关,回填结果,软删重录纠错)----------


@router.post("/{shipment_id}/customs-declarations", summary="录入报关(柜 LOADED/DEPARTED)")
async def create_customs(shipment_id: int, body: CustomsDeclarationCreateIn, request: Request,
                         current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    await customs_service.create(
        db, shipment_id=shipment_id,
        fields=body.model_dump(exclude={"attachment_ids"}),
        attachment_ids=body.attachment_ids, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    ship = await shipment_service.get_order(db, shipment_id)
    return success(await _detail_payload(db, ship))


@router.patch("/{shipment_id}/customs-declarations/{decl_id}",
              summary="改报关 / 回填放行 / 全量替换附件(乐观锁)")
async def update_customs(shipment_id: int, decl_id: int, body: CustomsDeclarationUpdateIn,
                         request: Request, current: CurrentUser = _MANAGE,
                         db: AsyncSession = Depends(get_db)):
    await customs_service.update(
        db, shipment_id=shipment_id, decl_id=decl_id,
        fields=body.model_dump(exclude_unset=True,
                               exclude={"expected_updated_at", "attachment_ids"}),
        attachment_ids=body.attachment_ids, expected_updated_at=body.expected_updated_at,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    ship = await shipment_service.get_order(db, shipment_id)
    return success(await _detail_payload(db, ship))


@router.delete("/{shipment_id}/customs-declarations/{decl_id}", summary="作废报关(归档附件)")
async def delete_customs(shipment_id: int, decl_id: int, request: Request,
                         current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    await customs_service.delete(
        db, shipment_id=shipment_id, decl_id=decl_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    ship = await shipment_service.get_order(db, shipment_id)
    return success(await _detail_payload(db, ship))
