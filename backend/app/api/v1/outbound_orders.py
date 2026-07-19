"""出库单路由 /api/v1/outbound-orders。销售单×柜双锚定;确认装柜=唯一扣库存事件。

守 outbound:manage(写)/ outbound:read(读)。出库单/行零金额列(纯仓单,契约 §3),
读投影天然无红线;应收(客户售价)不经本 API 回显,走 /receivables(整表 receivable:read 门控)。
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
from app.schemas.outbound_order import (
    OutboundOrderCreateIn,
    OutboundOrderLineOut,
    OutboundOrderListItem,
    OutboundOrderOut,
    OutboundOrderRevertIn,
    OutboundOrderUpdateIn,
)
from app.services import outbound_service, unit_service

router = APIRouter(prefix="/outbound-orders", tags=["outbound-orders"])

_READ = Depends(require_any_permission(Permissions.OUTBOUND_READ, Permissions.OUTBOUND_MANAGE))
_MANAGE = Depends(require_permission(Permissions.OUTBOUND_MANAGE))


async def _detail_payload(db, order) -> dict:
    lines = await outbound_service.list_line_views(db, order.id)
    parties = await outbound_service.resolve_order_parties(db, order)
    return {
        "order": OutboundOrderOut.build(order, parties),
        "lines": await unit_service.translate_unit_snapshots(
            db, [OutboundOrderLineOut.model_validate(ln).model_dump() for ln in lines]),
    }


@router.post("", summary="基于 CONFIRMED SO + OPEN 柜建出库单(草稿)")
async def create_outbound_order(body: OutboundOrderCreateIn, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await outbound_service.create_order(
        db, sales_order_id=body.sales_order_id, shipment_id=body.shipment_id, note=body.note,
        lines=[ln.model_dump() for ln in body.lines], actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, order))


@router.get("", summary="出库单列表(筛选/分页)")
async def list_outbound_orders(page_params: PageParams = Depends(), status: str | None = None,
                               shipment_id: int | None = None, sales_order_id: int | None = None,
                               keyword: str | None = None,
                               _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await outbound_service.list_orders(
        db, status=status, shipment_id=shipment_id, sales_order_id=sales_order_id,
        keyword=keyword, page=page_params.page, size=page_params.size)
    return success(Page(
        items=[OutboundOrderListItem.model_validate(it).model_dump() for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/{order_id}", summary="取出库单(含行 + SO/柜 摘要)")
async def get_outbound_order(order_id: int, _current: CurrentUser = _READ,
                             db: AsyncSession = Depends(get_db)):
    order = await outbound_service.get_order(db, order_id)
    return success(await _detail_payload(db, order))


@router.put("/{order_id}", summary="编辑草稿出库单(整单重写,乐观锁)")
async def update_outbound_order(order_id: int, body: OutboundOrderUpdateIn, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await outbound_service.save_order(
        db, order_id=order_id, note=body.note, lines=[ln.model_dump() for ln in body.lines],
        expected_updated_at=body.expected_updated_at, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, order))


@router.post("/{order_id}/confirm", summary="确认装柜(DRAFT→ISSUED,扣库存+生成应收)")
async def confirm_outbound_order(order_id: int, request: Request,
                                 current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await outbound_service.confirm_order(
        db, order_id=order_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(await _detail_payload(db, order))


@router.post("/{order_id}/revert", summary="撤销出库(ISSUED→DRAFT,作废应收)")
async def revert_outbound_order(order_id: int, body: OutboundOrderRevertIn, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await outbound_service.revert_order(
        db, order_id=order_id, void_reason=body.void_reason, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, order))


@router.post("/{order_id}/cancel", summary="取消出库单(仅草稿)")
async def cancel_outbound_order(order_id: int, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    order = await outbound_service.cancel_order(
        db, order_id=order_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(await _detail_payload(db, order))
