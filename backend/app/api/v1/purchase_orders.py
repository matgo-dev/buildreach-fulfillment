"""采购单路由 /api/v1/purchase-orders。基于 SO 建 PO + 状态机 + 红线脱敏。

守 purchase:manage(写)/ purchase:read(读)。🔴采购价/金额对无 purchase:read_cost 者后端置 null
(脱敏在响应 schema 构造工厂 PurchaseOrderOut.build/LineOut.build,见 schemas/purchase_order.py)。
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.inbound_order import RelatedInboundOrderItem
from app.schemas.purchase_order import (
    PurchaseOrderCreateIn,
    PurchaseOrderLineOut,
    PurchaseOrderListItem,
    PurchaseOrderOut,
    PurchaseOrderUpdateIn,
)
from app.services import inbound_order_service, purchase_order_service

router = APIRouter(prefix="/purchase-orders", tags=["purchase-orders"])

_READ = Depends(require_any_permission(Permissions.PURCHASE_READ, Permissions.PURCHASE_MANAGE))
_MANAGE = Depends(require_permission(Permissions.PURCHASE_MANAGE))


def _can_see_cost(current: CurrentUser) -> bool:
    return Permissions.PURCHASE_READ_COST in current.permissions


async def _detail_payload(db, po, current) -> dict:
    ccost = _can_see_cost(current)
    parties = await purchase_order_service.resolve_order_parties(db, po)
    lines = await purchase_order_service.list_lines(db, po.id)
    # 收货进度(轴2 派生)+ 行级在途/已入(入库步增强,不新增成本暴露)。
    line_ids = [ln.id for ln in lines]
    inbounded = await inbound_order_service.compute_inbounded_qty(db, line_ids)
    received = await inbound_order_service.compute_received_qty(db, line_ids)
    # 进度直接由上面已取的 received + 行 qty 派生,不再重查(共用 receipt_progress_from 单一口径)。
    progress = inbound_order_service.receipt_progress_from(
        received, {ln.id: Decimal(str(ln.qty)) for ln in lines})
    line_dicts = []
    for ln in lines:
        d = PurchaseOrderLineOut.build(ln, can_see_cost=ccost)
        rcv = received.get(ln.id)
        inb = inbounded.get(ln.id)
        d["received_qty"] = float(rcv) if rcv is not None else 0.0
        d["in_transit_qty"] = float((inb or 0) - (rcv or 0))
        line_dicts.append(d)
    related_inbound = await inbound_order_service.list_related_by_purchase_order(db, po.id)
    return {
        "order": PurchaseOrderOut.build(po, {
            **parties,
            "receipt_progress": progress,
        }, can_see_cost=ccost),
        "lines": line_dicts,
        "inbound_orders": [RelatedInboundOrderItem.model_validate(r).model_dump()
                           for r in related_inbound],
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
    po_ids = [it["id"] for it in items]
    # 收货进度徽标(轴2 派生,一次聚合覆盖本页 PO;不新增成本暴露)。
    progress = await inbound_order_service.receipt_progress_for_purchase_orders(db, po_ids)
    # 次要在途信号:该 PO 已登记未收货的入库单数(与收货进度互补,不并入收货态)。
    in_transit = await inbound_order_service.in_transit_inbound_count_for_purchase_orders(
        db, po_ids)
    out = []
    for it in items:
        d = PurchaseOrderListItem.build(it, can_see_cost=ccost)
        d["receipt_progress"] = progress.get(it["id"])
        d["in_transit_count"] = in_transit.get(it["id"], 0)
        out.append(d)
    return success({"items": out, "total": total, "page": page, "size": size})


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
