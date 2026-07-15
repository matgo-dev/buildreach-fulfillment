"""销售单路由 /api/v1/sales-orders。读:列表(+采购进度徽标/筛选)+ 详情(含行 + 采购进度 + 关联PO区)。

创建走报价侧 POST /quotations/{id}/convert(转销售 = 报价终态转移)。SO 本步零改动(单据状态机)。
采购进度=派生(轴2),不改表;related_purchase_orders 仅 purchase:read 下发(供应商身份红线端点级门控)。
守 sales:read。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.purchase_order import RelatedPurchaseOrderItem
from app.schemas.sales_order import SalesOrderLineOut, SalesOrderListItem, SalesOrderOut
from app.services import purchase_order_service, sales_order_service

router = APIRouter(prefix="/sales-orders", tags=["sales-orders"])

_GUARD = Depends(require_permission(Permissions.SALES_READ))


@router.get("", summary="销售单列表(筛选/排序/分页/采购进度)")
async def list_sales_orders(
    status: str | None = None,
    customer_id: int | None = None,
    salesperson_id: int | None = None,
    purchase_progress: str | None = Query(
        None, pattern=r"^(NOT_ORDERED|PARTIALLY_ORDERED|FULLY_ORDERED)$"),
    sort: str = Query("created_at", pattern=r"^(created_at|total_amount)$"),
    dir: str = Query("desc", pattern=r"^(asc|desc)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    items, total = await sales_order_service.list_orders(
        db, status=status, customer_id=customer_id, salesperson_id=salesperson_id,
        purchase_progress=purchase_progress, sort=sort, dir=dir, page=page, size=size)
    return success({
        "items": [SalesOrderListItem.model_validate(it).model_dump() for it in items],
        "total": total, "page": page, "size": size,
    })


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
    if Permissions.PURCHASE_READ in current.permissions:
        can_see_cost = Permissions.PURCHASE_READ_COST in current.permissions
        related = await purchase_order_service.list_related_by_sales_order(db, order_id)
        order_out["related_purchase_orders"] = [
            RelatedPurchaseOrderItem.build(it, can_see_cost=can_see_cost) for it in related]

    line_outs = []
    for ln in lines:
        d = SalesOrderLineOut.model_validate(ln, from_attributes=True).model_dump()
        d["covered_qty"] = float(covered.get(ln.id, 0))
        line_outs.append(d)
    return success({"order": order_out, "lines": line_outs})
