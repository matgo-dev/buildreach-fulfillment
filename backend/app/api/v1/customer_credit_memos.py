from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.common import Page, PageParams
from app.schemas.customer_credit_memo import (
    CustomerCreditMemoCreateIn,
    CustomerCreditMemoOut,
    CustomerCreditMemoRejectIn,
)
from app.services import customer_credit_memo_service

router = APIRouter(prefix="/customer-credit-memos", tags=["customer-credit-memos"])

_READ = Depends(require_any_permission(
    Permissions.RECEIVABLE_READ,
    Permissions.RECEIPT_READ,
    Permissions.RECEIPT_MANAGE,
))
_CREATE = Depends(require_any_permission(
    Permissions.PURCHASE_MANAGE,
    Permissions.SALES_MANAGE,
    Permissions.RECEIPT_MANAGE,
))
_POST = Depends(require_permission(Permissions.RECEIPT_MANAGE))

_STATUS_RE = r"^(PENDING_APPROVAL|POSTED|REJECTED)$"


@router.post("", summary="创建客户余额贷项单")
async def create_customer_credit_memo(
    body: CustomerCreditMemoCreateIn,
    request: Request,
    current: CurrentUser = _CREATE,
    db: AsyncSession = Depends(get_db),
):
    memo = await customer_credit_memo_service.create_memo(
        db,
        inventory_disposition_order_id=body.inventory_disposition_order_id,
        amount=body.amount,
        reason=body.reason,
        actor_user_id=current.id,
        actor_user_email=current.email,
        request=request,
    )
    return success(CustomerCreditMemoOut.build(memo))


@router.get("", summary="客户余额贷项单列表")
async def list_customer_credit_memos(
    page_params: PageParams = Depends(),
    status: str | None = Query(None, pattern=_STATUS_RE),
    customer_id: int | None = None,
    sales_order_id: int | None = None,
    inventory_disposition_order_id: int | None = None,
    _current: CurrentUser = _READ,
    db: AsyncSession = Depends(get_db),
):
    items, total = await customer_credit_memo_service.list_memos(
        db,
        status=status,
        customer_id=customer_id,
        sales_order_id=sales_order_id,
        inventory_disposition_order_id=inventory_disposition_order_id,
        page=page_params.page,
        size=page_params.size,
    )
    return success(Page(
        items=[CustomerCreditMemoOut.build(item) for item in items],
        total=total,
        page=page_params.page,
        size=page_params.size,
    ).model_dump())


@router.get("/{memo_id}", summary="客户余额贷项单详情")
async def get_customer_credit_memo(
    memo_id: int,
    _current: CurrentUser = _READ,
    db: AsyncSession = Depends(get_db),
):
    memo = await customer_credit_memo_service.get(db, memo_id)
    return success(CustomerCreditMemoOut.build(memo))


@router.post("/{memo_id}/post", summary="过账客户余额贷项单")
async def post_customer_credit_memo(
    memo_id: int,
    request: Request,
    current: CurrentUser = _POST,
    db: AsyncSession = Depends(get_db),
):
    memo = await customer_credit_memo_service.post_memo(
        db,
        memo_id=memo_id,
        actor_user_id=current.id,
        actor_user_email=current.email,
        request=request,
    )
    return success(CustomerCreditMemoOut.build(memo))


@router.post("/{memo_id}/reject", summary="驳回客户余额贷项单")
async def reject_customer_credit_memo(
    memo_id: int,
    body: CustomerCreditMemoRejectIn,
    request: Request,
    current: CurrentUser = _POST,
    db: AsyncSession = Depends(get_db),
):
    memo = await customer_credit_memo_service.reject_memo(
        db,
        memo_id=memo_id,
        reject_reason=body.reject_reason,
        actor_user_id=current.id,
        actor_user_email=current.email,
        request=request,
    )
    return success(CustomerCreditMemoOut.build(memo))


@router.post("/{memo_id}/resubmit", summary="重新提交被驳回的客户余额贷项单")
async def resubmit_customer_credit_memo(
    memo_id: int,
    request: Request,
    current: CurrentUser = _POST,
    db: AsyncSession = Depends(get_db),
):
    memo = await customer_credit_memo_service.resubmit_memo(
        db,
        memo_id=memo_id,
        actor_user_id=current.id,
        actor_user_email=current.email,
        request=request,
    )
    return success(CustomerCreditMemoOut.build(memo))
