"""应收款路由 /api/v1/receivables。P0 只读账层。

🔴 整端点红线门:守 receivable:read(整域含客户售价);无此权限 403,不做字段级脱敏
(镜像 payables 门控)。收款/核销 = 财务步(此处不建 receivable:manage)。
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
from app.schemas.receivable import ReceivableListItem
from app.services import receivable_service

router = APIRouter(prefix="/receivables", tags=["receivables"])

_READ = Depends(require_permission(Permissions.RECEIVABLE_READ))


@router.get("", summary="应收款列表(仅活动行;客户/状态/币种/搜索筛选)")
async def list_receivables(page_params: PageParams = Depends(), customer_id: int | None = None,
                           currency: str | None = None,
                           status: str | None = Query(
                               None, pattern=r"^(UNPAID|PARTIALLY_PAID|PAID)$"),
                           q: str | None = None,
                           _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await receivable_service.list_receivables(
        db, customer_id=customer_id, currency=currency, status=status, q=q,
        page=page_params.page, size=page_params.size)
    return success(Page(
        items=[ReceivableListItem.build(it) for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())
