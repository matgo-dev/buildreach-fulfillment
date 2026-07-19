"""销售单路由 /api/v1/sales-orders。读:列表(+采购进度徽标/筛选)+ 详情(含行 + 采购进度 + 关联PO区)。
写:整单取消(守 sales:manage;创建仍走报价侧 POST /quotations/{id}/convert)。

采购进度=派生(轴2),不改表;related_purchase_orders 仅 purchase:read 下发(供应商身份红线端点级门控)。
读守 sales:read。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import has_permission, require_permission
from app.rbac.redaction import can_see_cost
from app.schemas.common import Page, PageParams
from app.schemas.inventory import StockBalanceRow
from app.schemas.outbound_order import OutboundableLineOut, RelatedOutboundOrderItem
from app.schemas.purchase_order import RelatedPurchaseOrderItem
from app.schemas.sales_order import (
    SalesOrderCancelIn,
    SalesOrderLineOut,
    SalesOrderListItem,
    SalesOrderOut,
)
from app.services import (
    outbound_service,
    purchase_order_service,
    sales_order_service,
    stock_balance_service,
)
from app.services.stock_balance_service import StockScope

router = APIRouter(prefix="/sales-orders", tags=["sales-orders"])

_GUARD = Depends(require_permission(Permissions.SALES_READ))
_MANAGE = Depends(require_permission(Permissions.SALES_MANAGE))
_OUTBOUND_MANAGE = Depends(require_permission(Permissions.OUTBOUND_MANAGE))


@router.get("", summary="销售单列表(筛选/排序/分页/采购进度)")
async def list_sales_orders(
    page_params: PageParams = Depends(),
    status: str | None = None,
    customer_id: int | None = None,
    salesperson_id: int | None = None,
    no: str | None = None,
    purchase_progress: str | None = Query(
        None, pattern=r"^(NOT_ORDERED|PARTIALLY_ORDERED|FULLY_ORDERED)$"),
    purchasable_only: bool = False,
    sort: str = Query("created_at", pattern=r"^(created_at|total_amount)$"),
    dir: str = Query("desc", pattern=r"^(asc|desc)$"),
    _current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    items, total = await sales_order_service.list_orders(
        db, status=status, customer_id=customer_id, salesperson_id=salesperson_id,
        no=no, purchase_progress=purchase_progress, purchasable_only=purchasable_only,
        sort=sort, dir=dir, page=page_params.page, size=page_params.size)
    return success(Page(
        items=[SalesOrderListItem.model_validate(it).model_dump() for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.post("/{order_id}/cancel", summary="整单取消(CONFIRMED→CANCELLED,报价回锁档可重转)")
async def cancel_sales_order(
    order_id: int,
    body: SalesOrderCancelIn,
    request: Request,
    current: CurrentUser = _MANAGE,
    db: AsyncSession = Depends(get_db),
):
    so = await sales_order_service.cancel_order(
        db, order_id=order_id, reason=body.reason, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    lines = await sales_order_service.list_lines(db, order_id)
    parties = await sales_order_service.resolve_order_parties(db, so)
    return success({
        "order": {**SalesOrderOut.model_validate(so, from_attributes=True).model_dump(),
                  **parties},
        "lines": [SalesOrderLineOut.model_validate(ln, from_attributes=True).model_dump()
                  for ln in lines],
    })


@router.get("/{order_id}/outboundable-lines", summary="某 CONFIRMED SO 的可发行(出库建单器数据源)")
async def outboundable_lines(order_id: int, _current: CurrentUser = _OUTBOUND_MANAGE,
                             db: AsyncSession = Depends(get_db)):
    rows = await outbound_service.outboundable_lines(db, order_id)
    return success({"items": [OutboundableLineOut.model_validate(r).model_dump() for r in rows]})


@router.get("/{order_id}", summary="取销售单(含行 + 来源报价 + 采购进度/关联PO)")
async def get_sales_order(
    order_id: int,
    current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    so = await sales_order_service.get_order(db, order_id)
    lines = await sales_order_service.list_lines(db, order_id)
    parties = await sales_order_service.resolve_order_parties(db, so)
    # 采购进度(轴2 派生)+ 每行 covered_qty(数量,非红线):所有 sales:read 者可见。
    progress, covered = await purchase_order_service.compute_progress(db, order_id)

    order_out = {
        **SalesOrderOut.model_validate(so, from_attributes=True).model_dump(),
        **parties, "purchase_progress": progress,
    }
    # 关联采购单区:仅 purchase:read 者下发(SALES 拿不到供应商身份/金额)。
    if has_permission(current, Permissions.PURCHASE_READ):
        related = await purchase_order_service.list_related_by_sales_order(db, order_id)
        order_out["related_purchase_orders"] = [
            RelatedPurchaseOrderItem.build(it, can_see_cost=can_see_cost(current))
            for it in related]
    # 关联出库单区:仅 outbound:read 者下发(单号/柜/状态,链接详情;无金额)。
    if has_permission(current, Permissions.OUTBOUND_READ):
        related_ob = await outbound_service.list_related_by_sales_order(db, order_id)
        order_out["related_outbound_orders"] = [
            RelatedOutboundOrderItem.model_validate(it).model_dump() for it in related_ob]
    # 库存跟踪块:仅 inventory:read 者下发(响应键存在与否驱动前端,后端脱敏非前端隐藏)。
    # scope=ALL:该 SO 全部 (sku) 行含已入 0,对照订购;无成本/供应商字段 → 非红线。
    if has_permission(current, Permissions.INVENTORY_READ):
        stock_rows, _ = await stock_balance_service.compute_stock_balance(
            db, sales_order_id=order_id, scope=StockScope.ALL)
        # 与 /inventory 同一 schema 校验(单一契约,防两条序列化路径漂移)。
        order_out["stock_balances"] = [
            StockBalanceRow(**r).model_dump() for r in stock_rows]

    line_outs = []
    for ln in lines:
        d = SalesOrderLineOut.model_validate(ln, from_attributes=True).model_dump()
        d["covered_qty"] = float(covered.get(ln.id, 0))
        line_outs.append(d)
    return success({"order": order_out, "lines": line_outs})
