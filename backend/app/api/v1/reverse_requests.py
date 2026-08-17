from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_any_permission, require_permission
from app.schemas.common import Page, PageParams
from app.schemas.reverse_request import (
    ReverseRequestApproveIn,
    ReverseRequestCompleteIn,
    ReverseRequestCreateIn,
    ReverseRequestLineOut,
    ReverseRequestListItem,
    ReverseRequestOut,
    ReverseRequestRejectIn,
)
from app.services import reverse_request_service, unit_service

router = APIRouter(prefix="/reverse-requests", tags=["reverse-requests"])

_READ = Depends(require_any_permission(Permissions.REVERSE_READ, Permissions.REVERSE_MANAGE))
_MANAGE = Depends(require_permission(Permissions.REVERSE_MANAGE))


async def _detail_payload(db: AsyncSession, req) -> dict:
    parties = await reverse_request_service.resolve_request_parties(db, req)
    lines = [ReverseRequestLineOut.build(ln)
             for ln in await reverse_request_service.list_lines(db, req.id)]
    await unit_service.translate_unit_snapshots(db, lines)
    return {
        "request": ReverseRequestOut.build(req, parties),
        "lines": lines,
    }


@router.post("", summary="创建出库前履约中取消申请")
async def create_reverse_request(body: ReverseRequestCreateIn, request: Request,
                                 current: CurrentUser = _MANAGE,
                                 db: AsyncSession = Depends(get_db)):
    req = await reverse_request_service.create_fulfillment_cancel(
        db, inbound_order_id=body.inbound_order_id, reason=body.reason,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, req))


@router.get("", summary="逆向申请列表")
async def list_reverse_requests(page_params: PageParams = Depends(), status: str | None = None,
                                sales_order_id: int | None = None,
                                inbound_order_id: int | None = None,
                                q: str | None = None,
                                _current: CurrentUser = _READ,
                                db: AsyncSession = Depends(get_db)):
    items, total = await reverse_request_service.list_requests(
        db, status=status, sales_order_id=sales_order_id, inbound_order_id=inbound_order_id,
        q=q, page=page_params.page, size=page_params.size)
    return success(Page(
        items=[ReverseRequestListItem.model_validate(it).model_dump() for it in items],
        total=total, page=page_params.page, size=page_params.size).model_dump())


@router.get("/{request_id}", summary="逆向申请详情")
async def get_reverse_request(request_id: int, _current: CurrentUser = _READ,
                              db: AsyncSession = Depends(get_db)):
    req = await reverse_request_service.get_request(db, request_id)
    return success(await _detail_payload(db, req))


@router.post("/{request_id}/approve", summary="审核通过逆向申请")
async def approve_reverse_request(request_id: int, body: ReverseRequestApproveIn,
                                  request: Request, current: CurrentUser = _MANAGE,
                                  db: AsyncSession = Depends(get_db)):
    req = await reverse_request_service.approve(
        db, request_id=request_id, supplier_resolution=body.supplier_resolution,
        review_note=body.review_note, actor_user_id=current.id,
        actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, req))


@router.post("/{request_id}/reject", summary="驳回逆向申请")
async def reject_reverse_request(request_id: int, body: ReverseRequestRejectIn,
                                 request: Request, current: CurrentUser = _MANAGE,
                                 db: AsyncSession = Depends(get_db)):
    req = await reverse_request_service.reject(
        db, request_id=request_id, review_note=body.review_note,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, req))


@router.post("/{request_id}/complete", summary="关闭逆向申请")
async def complete_reverse_request(request_id: int, body: ReverseRequestCompleteIn,
                                   request: Request, current: CurrentUser = _MANAGE,
                                   db: AsyncSession = Depends(get_db)):
    req = await reverse_request_service.complete(
        db, request_id=request_id, completion_note=body.completion_note,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _detail_payload(db, req))
