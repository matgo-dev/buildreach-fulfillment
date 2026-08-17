"""付款单路由 /api/v1/payments(付侧实层 + 核销)。🔴红线整端点门控。

守 payment:read(读)/ payment:manage(登记/核销/反核销)。付款关联供应商 + 采购付款金额,
属红线域:无 payment:read 者整端点 403,不下发付款单与付侧核销真值(后端脱敏,非前端隐藏)。
无 claim(supplier 必填,无待认领态)。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.common import Page, PageParams
from app.schemas.payment import PaymentCreateIn, PaymentVoidIn
from app.schemas.receipt import ManualAllocateIn
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])

_READ = Depends(require_any_permission(Permissions.PAYMENT_READ, Permissions.PAYMENT_MANAGE))
_MANAGE = Depends(require_permission(Permissions.PAYMENT_MANAGE))

_STATUS_RE = r"^(UNALLOCATED|PARTIALLY_ALLOCATED|FULLY_ALLOCATED|VOIDED)$"


@router.post("", summary="登记付款(同事务自动核销未结应付,多余金额留存为预付)")
async def create_payment(body: PaymentCreateIn, request: Request,
                         current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    payment = await payment_service.register(
        db, fields=body.model_dump(), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await payment_service.build_detail(db, payment))


@router.get("", summary="付款单列表(供应商/币种/状态/搜索筛选)")
async def list_payments(page_params: PageParams = Depends(), supplier_id: int | None = None,
                        currency: str | None = None,
                        status: str | None = Query(None, pattern=_STATUS_RE),
                        q: str | None = None,
                        _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await payment_service.list_payments(
        db, supplier_id=supplier_id, currency=currency, status=status, q=q,
        page=page_params.page, size=page_params.size)
    return success(Page(items=items, total=total, page=page_params.page,
                        size=page_params.size).model_dump())


@router.get("/{payment_id}", summary="付款单详情(嵌活动核销记录)")
async def get_payment(payment_id: int, _current: CurrentUser = _READ,
                      db: AsyncSession = Depends(get_db)):
    payment = await payment_service.get(db, payment_id)
    return success(await payment_service.build_detail(db, payment))


@router.post("/{payment_id}/void", summary="作废纠错(零活动核销才可作废)")
async def void_payment(payment_id: int, body: PaymentVoidIn, request: Request,
                       current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    payment = await payment_service.void(
        db, payment_id=payment_id, void_reason=body.void_reason, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await payment_service.build_detail(db, payment))


@router.post("/{payment_id}/allocations", summary="人工核销(选应付,金额自动取满 min)")
async def allocate_payment(payment_id: int, body: ManualAllocateIn, request: Request,
                           current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    payment = await payment_service.manual_allocate(
        db, payment_id=payment_id, account_id=body.account_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await payment_service.build_detail(db, payment))


# 反核销:核销记录独立路径(无单号,用 id)。reason 走 query(DELETE body 公网不可靠)。
alloc_router = APIRouter(prefix="/payment-allocations", tags=["payments"])


@alloc_router.delete("/{alloc_id}", summary="反核销(软删核销记录;金额退回未分配 + 未结应付恢复)")
async def reverse_payment_allocation(alloc_id: int, request: Request,
                                     reverse_reason: str | None = Query(default=None, max_length=500),
                                     current: CurrentUser = _MANAGE,
                                     db: AsyncSession = Depends(get_db)):
    payment = await payment_service.reverse_allocation(
        db, alloc_id=alloc_id, reverse_reason=reverse_reason, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await payment_service.build_detail(db, payment))
