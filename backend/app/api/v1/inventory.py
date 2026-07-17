"""库存路由 /api/v1/inventory —— 订单库存跟踪列表(纯派生只读,契约 §3)。

单一读端点,无写口(库存无手工调整/盘点,数字全由单据链派生)。无成本/供应商/金额字段
→ 零红线、零脱敏分支。守 inventory:read(PURCHASER/SALES;ADMIN 不授,Q25 职责分离)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.common import Page, PageParams
from app.schemas.inventory import StockBalanceRow
from app.services import stock_balance_service
from app.services.stock_balance_service import StockScope

router = APIRouter(prefix="/inventory", tags=["inventory"])

_GUARD = Depends(require_permission(Permissions.INVENTORY_READ))


@router.get("", summary="订单库存跟踪列表(派生四量 / 筛选 / 分页)")
async def list_inventory(
    page_params: PageParams = Depends(),
    sales_order_id: int | None = None,
    sku_id: int | None = None,
    q: str | None = None,
    # pattern 从 PAGE_SCOPES 派生(单一源头);ALL 仅内部 SO 详情块用,端点不可达。
    scope: str = Query(StockScope.AVAILABLE,
                       pattern=f"^({'|'.join(StockScope.PAGE_SCOPES)})$"),
    _current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    rows, total = await stock_balance_service.compute_stock_balance(
        db, sales_order_id=sales_order_id, sku_id=sku_id, q=q, scope=scope,
        page=page_params.page, size=page_params.size)
    return success(Page(
        items=[StockBalanceRow(**r).model_dump() for r in rows],
        total=total, page=page_params.page, size=page_params.size).model_dump())
