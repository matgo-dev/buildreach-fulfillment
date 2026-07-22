"""应付款路由 /api/v1/payables。P0 只读账层。

🔴 整端点红线门:守 payable:read(整域含供应商 + 成本);无此权限 403,不做字段级脱敏。
付款/核销 = 财务步(此处不建 payable:manage)。
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
from app.schemas.payable import PayableListItem
from app.services import payable_service

router = APIRouter(prefix="/payables", tags=["payables"])

_READ = Depends(require_permission(Permissions.PAYABLE_READ))


@router.get("", summary="应付款列表(仅活动行;状态/搜索/供应商/币种筛选)")
async def list_payables(page_params: PageParams = Depends(),
                        supplier_id: int | None = None, currency: str | None = None,
                        status: str | None = Query(
                            None, pattern=r"^(UNPAID|PARTIALLY_PAID|PAID)$"),
                        q: str | None = None,
                        _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await payable_service.list_payables(
        db, supplier_id=supplier_id, currency=currency, status=status, q=q,
        page=page_params.page, size=page_params.size)
    return success(Page(
        items=[PayableListItem.build(it) for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/{payable_id}", summary="应付款详情(嵌活动核销记录:哪笔付款冲了多少)· 🔴红线")
async def get_payable(payable_id: int, _current: CurrentUser = _READ,
                      db: AsyncSession = Depends(get_db)):
    return success(await payable_service.get_detail(db, payable_id))
