"""采购单路由 /api/v1/purchase-orders。基于 SO 建 PO + 状态机 + 红线脱敏。

守 purchase:manage(写)/ purchase:read(读)。🔴采购价/金额对无 purchase:read_cost 者后端置 null
(脱敏在响应 schema 构造工厂 PurchaseOrderOut.build/LineOut.build,见 schemas/purchase_order.py)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.purchase_order import (
    PurchaseOrderCreateIn,
    PurchaseOrderLineOut,
    PurchaseOrderListItem,
    PurchaseOrderOut,
    PurchaseOrderUpdateIn,
)
from app.services import purchase_order_service

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])

_READ = Depends(require_any_permission(Permissions.PURCHASE_READ, Permissions.PURCHASE_MANAGE))
_MANAGE = Depends(require_permission(Permissions.PURCHASE_MANAGE))


def _can_see_cost(current: CurrentUser) -> bool:
    return Permissions.PURCHASE_READ_COST in current.permissions


async def _detail_payload(db, po, current) -> dict:
    ccost = _can_see_cost(current)
    parties = await purchase_order_service.resolve_order_parties(db, po)
    lines = await purchase_order_service.list_lines(db, po.id)
    return {
        "order": PurchaseOrderOut.build(po, parties, can_see_cost=ccost),
        "lines": [PurchaseOrderLineOut.build(ln, can_see_cost=ccost) for ln in lines],
    }


@router.post("", summary="基于 SO 建采购单(单一供应商)")
async def create_purchase_order(body: PurchaseOrderCreateIn, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    po = await purchase_order_service.create_order(
        db, source_sales_order_id=body.source_sales_order_id, supplier_id=body.supplier_id,
        currency=body.currency, remark=body.remark,
        lines=[ln.model_dump() for ln in body.lines],
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, po, current))


@router.get("", summary="采购单列表(筛选/分页)")
async def list_purchase_orders(status: str | None = None, supplier_id: int | None = None,
                               source_sales_order_id: int | None = None,
                               source_sales_order_no: str | None = None,
                               page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                               current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await purchase_order_service.list_orders(
        db, status=status, supplier_id=supplier_id,
        source_sales_order_id=source_sales_order_id,
        source_sales_order_no=source_sales_order_no, page=page, size=size)
    ccost = _can_see_cost(current)
    return success({
        "items": [PurchaseOrderListItem.build(it, can_see_cost=ccost) for it in items],
        "total": total, "page": page, "size": size,
    })


@router.get("/purchasable-lines", summary="某 SO 的可采行(建单器数据源)")
async def purchasable_lines(source_sales_order_id: int = Query(...),
                            _current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    rows = await purchase_order_service.purchasable_lines(db, source_sales_order_id)
    return success({"items": rows})


@router.get("/{order_id}", summary="取采购单(含行)")
async def get_purchase_order(order_id: int, current: CurrentUser = _READ,
                             db: AsyncSession = Depends(get_db)):
    po = await purchase_order_service.get_order(db, order_id)
    return success(await _detail_payload(db, po, current))


@router.put("/{order_id}", summary="编辑草稿采购单(整单对账+乐观锁)")
async def update_purchase_order(order_id: int, body: PurchaseOrderUpdateIn, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    po = await purchase_order_service.save_order(
        db, order_id=order_id, supplier_id=body.supplier_id, currency=body.currency,
        remark=body.remark, lines=[ln.model_dump() for ln in body.lines],
        expected_updated_at=body.expected_updated_at, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, po, current))


@router.delete("/{order_id}", summary="硬删草稿采购单")
async def delete_purchase_order(order_id: int, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    await purchase_order_service.delete_order(
        db, order_id=order_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(None)


@router.post("/{order_id}/confirm", summary="确认采购单(下单 DRAFT→CONFIRMED)")
async def confirm_purchase_order(order_id: int, request: Request,
                                 current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    po = await purchase_order_service.confirm_order(
        db, order_id=order_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(await _detail_payload(db, po, current))


@router.post("/{order_id}/cancel", summary="取消采购单(→CANCELLED)")
async def cancel_purchase_order(order_id: int, request: Request,
                                current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    po = await purchase_order_service.cancel_order(
        db, order_id=order_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(await _detail_payload(db, po, current))
