"""报价单路由 /api/v1/quotations。8 端点:列表/建/取/整单保存/删/锁档/解锁/作废。

行录入走整单 POST/PUT(内联表格 + 一次保存,按行 id 对账 + 乐观锁);状态跃迁独立 action。
锁档/转销售留下游增量(CONVERTED 在矩阵占位)。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.models.quotation import QuotationStatus
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.rbac.redaction import can_see_price
from app.schemas.common import Page, PageParams
from app.schemas.quotation import (
    QuotationLineOut,
    QuotationListItem,
    QuotationOrderOut,
    QuotationSaveIn,
    QuotationUpdateIn,
    QuotationVoidIn,
)
from app.schemas.sales_order import SalesOrderLineOut, SalesOrderOut
from app.services import quotation_service, sales_order_service, unit_service

router = APIRouter(prefix="/quotations", tags=["quotations"])

_GUARD = Depends(require_permission(Permissions.QUOTE_MANAGE))


def _order_out(order) -> dict:
    return QuotationOrderOut.model_validate(order, from_attributes=True).model_dump()


@router.get("", summary="报价列表(筛选/排序/分页)")
async def list_quotations(
    page_params: PageParams = Depends(),
    status: str | None = None,
    customer_id: int | None = None,
    salesperson_id: int | None = None,
    keyword: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    sort: str = Query("created_at", pattern=r"^(created_at|total_amount)$"),
    _current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    items, total = await quotation_service.list_orders(
        db, status=status, customer_id=customer_id, salesperson_id=salesperson_id,
        keyword=keyword, created_from=created_from, created_to=created_to,
        sort=sort, page=page_params.page, size=page_params.size)
    return success(Page(
        items=[QuotationListItem.model_validate(it).model_dump() for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.post("", summary="新建报价(整单:表头 + 行数组)")
async def create_quotation(
    body: QuotationSaveIn,
    request: Request,
    current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    order = await quotation_service.save_order(
        db, order_id=None, customer_id=body.customer_id, currency=body.currency,
        salesperson_id=body.salesperson_id, valid_until=body.valid_until,
        summary=body.summary, language=body.language, remark=body.remark,
        lines=[ln.model_dump() for ln in body.lines],
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(_order_out(order))


@router.get("/{order_id}", summary="取报价单(含行)")
async def get_quotation(
    order_id: int,
    _current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    order = await quotation_service.get_order(db, order_id)
    lines = await quotation_service.list_lines(db, order_id)
    parties = await quotation_service.resolve_order_parties(db, order)
    # 反查出口:已转销售的报价带 order.sales_order={id,no}(前端「已转→跳销售单」);未转为 None。
    sales_order = (await sales_order_service.find_by_source_quotation(db, order_id)
                   if order.status == QuotationStatus.CONVERTED else None)
    return success({
        "order": {**_order_out(order), **parties, "sales_order": sales_order},
        "lines": await unit_service.translate_unit_snapshots(
            db, [QuotationLineOut.model_validate(l, from_attributes=True).model_dump()
                 for l in lines]),
    })


@router.put("/{order_id}", summary="整单保存草稿(行对账 + 乐观锁)")
async def update_quotation(
    order_id: int,
    body: QuotationUpdateIn,
    request: Request,
    current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    order = await quotation_service.save_order(
        db, order_id=order_id, customer_id=body.customer_id, currency=body.currency,
        salesperson_id=body.salesperson_id, valid_until=body.valid_until,
        summary=body.summary, language=body.language, remark=body.remark,
        lines=[ln.model_dump() for ln in body.lines],
        expected_updated_at=body.expected_updated_at,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(_order_out(order))


@router.post("/{order_id}/lock", summary="锁档(DRAFT→LOCKED)")
async def lock_quotation(
    order_id: int,
    request: Request,
    current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    order = await quotation_service.lock_order(
        db, order_id=order_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(_order_out(order))


@router.post("/{order_id}/unlock", summary="解锁(LOCKED→DRAFT)")
async def unlock_quotation(
    order_id: int,
    request: Request,
    current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    order = await quotation_service.unlock_order(
        db, order_id=order_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(_order_out(order))


@router.post("/{order_id}/void", summary="作废(DRAFT/LOCKED→VOID)")
async def void_quotation(
    order_id: int,
    request: Request,
    body: QuotationVoidIn | None = None,
    current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    order = await quotation_service.void_order(
        db, order_id=order_id, reason=(body.reason if body else None),
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(_order_out(order))


@router.post("/{order_id}/convert", summary="转销售单(LOCKED→CONVERTED,建销售单)")
async def convert_quotation(
    order_id: int,
    request: Request,
    current: CurrentUser = _GUARD,
    db: AsyncSession = Depends(get_db),
):
    # 转换是报价终态转移(与 lock/unlock/void 同族),守 quote:manage;销售单本增量无独立写面。
    so = await sales_order_service.convert_quotation(
        db, quotation_id=order_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    lines = await sales_order_service.list_lines(db, so.id)
    parties = await sales_order_service.resolve_order_parties(db, so)
    # 守 quote:manage(仅 SALES,恒持 receivable:read);经 build 保持「无裸 dump」不变式。
    price_visible = can_see_price(current)
    return success({
        "order": SalesOrderOut.build(so, parties, can_see_price=price_visible),
        "lines": await unit_service.translate_unit_snapshots(
            db, [SalesOrderLineOut.build(l, can_see_price=price_visible)
                 for l in lines]),
    })
