"""销售单路由 /api/v1/sales-orders。本增量只读:列表 + 详情(含行 + 来源报价号)。

创建走报价侧 POST /quotations/{id}/convert(转销售 = 报价终态转移);销售单写面(编辑/取消)
+ 完整状态机留给「转采购」增量。守 sales:read。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.sales_order import SalesOrderLineOut, SalesOrderListItem, SalesOrderOut
from app.services import sales_order_service

router = APIRouter(prefix="/sales-orders", tags=["sales-orders"])

_GUARD = Depends(require_permission(Permissions.SALES_READ))


@router.get("", summary="销售单列表(筛选/排序/分页)")
async def list_sales_orders(
    status: str | None = None,
    customer_id: int | None = None,
    salesperson_id: int | None = None,
    sort: str = Query("created_at", pattern=r"^(created_at|total_amount)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    items, total = await sales_order_service.list_orders(
        db, status=status, customer_id=customer_id, salesperson_id=salesperson_id,
        sort=sort, page=page, size=size)
    return success({
        "items": [SalesOrderListItem.model_validate(it).model_dump() for it in items],
        "total": total, "page": page, "size": size,
    })


@router.get("/{order_id}", summary="取销售单(含行 + 来源报价)")
async def get_sales_order(
    order_id: int,
    _current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    so = await sales_order_service.get_order(db, order_id)
    lines = await sales_order_service.list_lines(db, order_id)
    parties = await sales_order_service.resolve_order_parties(db, so)
    return success({
        "order": {**SalesOrderOut.model_validate(so, from_attributes=True).model_dump(), **parties},
        "lines": [SalesOrderLineOut.model_validate(l, from_attributes=True).model_dump()
                  for l in lines],
    })
