"""收款单路由 /api/v1/receipts(收侧实层 + 核销)。

守 receipt:read(读)/ receipt:manage(登记/认领/核销/反核销)。收款 = 客户售价侧,非红线
(同 receivable:read 域)。详情内嵌应收明细额按 D9 门控:无 receivable:read 者脱敏为 null。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import has_permission, require_any_permission, require_permission
from app.schemas.common import Page, PageParams
from app.schemas.receipt import (
    ManualAllocateIn,
    ReceiptClaimIn,
    ReceiptCreateIn,
    ReceiptVoidIn,
)
from app.services import receipt_service

router = APIRouter(prefix="/receipts", tags=["receipts"])

_READ = Depends(require_any_permission(Permissions.RECEIPT_READ, Permissions.RECEIPT_MANAGE))
_MANAGE = Depends(require_permission(Permissions.RECEIPT_MANAGE))

_STATUS_RE = r"^(UNCLAIMED|UNALLOCATED|PARTIALLY_ALLOCATED|FULLY_ALLOCATED|VOIDED)$"


def _can_read_account(current: CurrentUser) -> bool:
    return has_permission(current, Permissions.RECEIVABLE_READ)


@router.post("", summary="登记收款(已认领则同事务自动核销)")
async def create_receipt(body: ReceiptCreateIn, request: Request,
                         current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    receipt = await receipt_service.register(
        db, fields=body.model_dump(), actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await receipt_service.build_detail(
        db, receipt, can_read_account=_can_read_account(current)))


@router.get("", summary="收款单列表(客户/币种/状态/搜索筛选)")
async def list_receipts(page_params: PageParams = Depends(), customer_id: int | None = None,
                        currency: str | None = None,
                        status: str | None = Query(None, pattern=_STATUS_RE),
                        q: str | None = None,
                        _current: CurrentUser = _READ, db: AsyncSession = Depends(get_db)):
    items, total = await receipt_service.list_receipts(
        db, customer_id=customer_id, currency=currency, status=status, q=q,
        page=page_params.page, size=page_params.size)
    return success(Page(items=items, total=total, page=page_params.page,
                        size=page_params.size).model_dump())


@router.get("/{receipt_id}", summary="收款单详情(嵌活动核销记录;应收额按 D9 门控)")
async def get_receipt(receipt_id: int, current: CurrentUser = _READ,
                      db: AsyncSession = Depends(get_db)):
    receipt = await receipt_service.get(db, receipt_id)
    return success(await receipt_service.build_detail(
        db, receipt, can_read_account=_can_read_account(current)))


@router.post("/{receipt_id}/claim", summary="认领客户(仅 UNCLAIMED;认领后自动核销)")
async def claim_receipt(receipt_id: int, body: ReceiptClaimIn, request: Request,
                        current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    receipt = await receipt_service.claim(
        db, receipt_id=receipt_id, customer_id=body.customer_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await receipt_service.build_detail(
        db, receipt, can_read_account=_can_read_account(current)))


@router.post("/{receipt_id}/void", summary="作废纠错(零活动核销才可作废;有核销先反核销)")
async def void_receipt(receipt_id: int, body: ReceiptVoidIn, request: Request,
                       current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    receipt = await receipt_service.void(
        db, receipt_id=receipt_id, void_reason=body.void_reason, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await receipt_service.build_detail(
        db, receipt, can_read_account=_can_read_account(current)))


@router.post("/{receipt_id}/allocations", summary="人工核销(选应收,金额自动取满 min)")
async def allocate_receipt(receipt_id: int, body: ManualAllocateIn, request: Request,
                           current: CurrentUser = _MANAGE, db: AsyncSession = Depends(get_db)):
    receipt = await receipt_service.manual_allocate(
        db, receipt_id=receipt_id, account_id=body.account_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await receipt_service.build_detail(
        db, receipt, can_read_account=_can_read_account(current)))


# 反核销:核销记录独立路径(核销记录无单号,用 id)。
alloc_router = APIRouter(prefix="/receipt-allocations", tags=["receipts"])


@alloc_router.delete("/{alloc_id}", summary="反核销(软删核销记录;金额退回未分配 + 未结应收恢复)")
async def reverse_receipt_allocation(alloc_id: int, request: Request,
                                     reverse_reason: str | None = Query(default=None, max_length=500),
                                     current: CurrentUser = _MANAGE,
                                     db: AsyncSession = Depends(get_db)):
    # reason 走 query(非 DELETE body):DELETE 携带 body 在公网代理/WAF 下常被剥离,不可靠。
    receipt = await receipt_service.reverse_allocation(
        db, alloc_id=alloc_id, reverse_reason=reverse_reason, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await receipt_service.build_detail(
        db, receipt, can_read_account=_can_read_account(current)))
