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
from app.rbac.guards import has_permission, require_permission
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
                           current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    # D10 提示位派生自收款域:无 receipt:read 者不下发(恒 False),权限跟数据走。
    items, total = await receivable_service.list_receivables(
        db, customer_id=customer_id, currency=currency, status=status, q=q,
        page=page_params.page, size=page_params.size,
        can_read_receipt=has_permission(current, Permissions.RECEIPT_READ))
    return success(Page(
        items=[ReceivableListItem.build(it) for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/{receivable_id}", summary="应收款详情(嵌活动核销记录:哪笔收款冲了多少)")
async def get_receivable(receivable_id: int, _current: CurrentUser = _READ,
                         db: AsyncSession = Depends(get_db)):
    return success(await receivable_service.get_detail(db, receivable_id))
