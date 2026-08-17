from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.common import Page, PageParams
from app.schemas.purchase_return import APCreditMemoOut, RejectIn
from app.services import purchase_return_service

router = APIRouter(prefix="/ap-credit-memos", tags=["ap-credit-memos"])

_READ = Depends(require_permission(Permissions.PAYABLE_READ))
_POST = Depends(require_permission(Permissions.PAYMENT_MANAGE))


@router.get("", summary="供应商贷项单列表")
async def list_ap_credit_memos(page_params: PageParams = Depends(),
                               status: str | None = Query(
                                   None, pattern=r"^(PENDING_APPROVAL|POSTED|REJECTED)$"),
                               supplier_id: int | None = None,
                               payable_id: int | None = None,
                               purchase_return_order_id: int | None = None,
                               _current: CurrentUser = _READ,
                               db: AsyncSession = Depends(get_db)):
    items, total = await purchase_return_service.list_credit_memos(
        db, status=status, supplier_id=supplier_id, payable_id=payable_id,
        purchase_return_order_id=purchase_return_order_id,
        page=page_params.page, size=page_params.size)
    return success(Page(
        items=[APCreditMemoOut.build(item) for item in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/{memo_id}", summary="供应商贷项单详情")
async def get_ap_credit_memo(memo_id: int, _current: CurrentUser = _READ,
                             db: AsyncSession = Depends(get_db)):
    memo = await purchase_return_service.get_credit_memo(db, memo_id)
    return success(APCreditMemoOut.build(memo))


@router.post("/{memo_id}/post", summary="过账供应商贷项单")
async def post_ap_credit_memo(memo_id: int, request: Request,
                              current: CurrentUser = _POST,
                              db: AsyncSession = Depends(get_db)):
    memo = await purchase_return_service.post_credit_memo(
        db, memo_id=memo_id, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(APCreditMemoOut.build(memo))


@router.post("/{memo_id}/reject", summary="驳回供应商贷项单")
async def reject_ap_credit_memo(memo_id: int, body: RejectIn, request: Request,
                                current: CurrentUser = _POST,
                                db: AsyncSession = Depends(get_db)):
    memo = await purchase_return_service.reject_credit_memo(
        db, memo_id=memo_id, reject_reason=body.reject_reason,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(APCreditMemoOut.build(memo))
