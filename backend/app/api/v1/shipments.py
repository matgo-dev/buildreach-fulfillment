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
from app.services import outbound_service, shipment_service

router = APIRouter(prefix="/shipments", tags=["shipments"])

_READ = Depends(require_any_permission(Permissions.SHIPMENT_READ, Permissions.SHIPMENT_MANAGE))
_MANAGE = Depends(require_permission(Permissions.SHIPMENT_MANAGE))


async def _detail_payload(db, ship) -> dict:
    outbounds = await outbound_service.list_orders(db, shipment_id=ship.id, size=200)
    count = await shipment_service.outbound_count(db, ship.id)
    return {
        "shipment": ShipmentOut.build(ship, {"outbound_count": count}),
        # 柜内出库单(组柜工作台);列=SO 号/柜/行数/件数/状态,无金额。
        "outbound_orders": [{
            "id": it["id"], "no": it["no"], "sales_order_id": it["sales_order_id"],
            "sales_order_no": it["sales_order_no"], "customer_display": it["customer_display"],
            "status": it["status"],
            "line_count": it["line_count"], "total_qty": it["total_qty"],
        } for it in outbounds[0]],
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
                         keyword: str | None = None,
                         _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await shipment_service.list_orders(
        db, status=status, keyword=keyword, page=page_params.page, size=page_params.size)
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
