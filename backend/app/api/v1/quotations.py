"""报价单路由 /api/v1/quotations。M1:建草稿 + 逐行录入(带快照)+ 取。锁档/转销售留 M2。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.quotation import (
    QuotationCreateIn,
    QuotationLineIn,
    QuotationLineOut,
    QuotationOrderOut,
)
from app.services import quotation_service

router = APIRouter(prefix="/quotations", tags=["quotations"])


@router.post("", summary="建报价草稿")
async def create_quotation(
    body: QuotationCreateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.QUOTE_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    order = await quotation_service.create_draft(
        db, customer_id=body.customer_id, currency=body.currency,
        valid_until=body.valid_until, remark=body.remark,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(QuotationOrderOut.model_validate(order, from_attributes=True).model_dump())


@router.post("/{order_id}/lines", summary="加报价行(带规格快照)")
async def add_line(
    order_id: int,
    body: QuotationLineIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.QUOTE_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    line = await quotation_service.add_line(
        db, order_id=order_id, sku_id=body.sku_id, unit_price=body.unit_price,
        qty=body.qty, name_snapshot=body.name_snapshot,
        spec_text_snapshot=body.spec_text_snapshot, unit_snapshot=body.unit_snapshot,
        sort_order=body.sort_order, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(QuotationLineOut.model_validate(line, from_attributes=True).model_dump())


@router.get("/{order_id}", summary="取报价单(含行)")
async def get_quotation(
    order_id: int,
    _current: CurrentUser = Depends(require_permission(Permissions.QUOTE_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    order = await quotation_service.get_order(db, order_id)
    lines = await quotation_service.list_lines(db, order_id)
    return success({
        "order": QuotationOrderOut.model_validate(order, from_attributes=True).model_dump(),
        "lines": [QuotationLineOut.model_validate(l, from_attributes=True).model_dump()
                  for l in lines],
    })
