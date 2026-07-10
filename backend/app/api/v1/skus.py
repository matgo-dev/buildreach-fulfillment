"""SKU 路由 /api/v1/skus。全端点:搜索(分页/派生可用性过滤)/详情/建/改/上下架/逻辑删。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.common import StatusPatchIn
from app.schemas.sku import SkuCreateIn, SkuUpdateIn, sku_out
from app.services import sku_service

router = APIRouter(prefix="/skus", tags=["skus"])


@router.get("", summary="搜 SKU(pg_trgm 模糊:名/规格/编码,支持 spu_id/分页/available 过滤)")
async def search_skus(
    q: str = "",
    spu_id: int | None = None,
    available: bool = Query(False, description="True: 仅返回 SKU/SPU 均 ACTIVE 未删的可选货"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await sku_service.search_skus(
        db, q, spu_id=spu_id, page=page, size=size, available=available)
    include_cost = Permissions.CATALOG_MANAGE in current.permissions
    items = [sku_out(r, include_cost=include_cost) for r in rows]
    return success({"items": items, "total": total, "page": page, "size": size})


@router.post("", summary="加 SKU")
async def create_sku(
    body: SkuCreateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.CATALOG_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    sku = await sku_service.create_sku(
        db, spu_id=body.spu_id, unit=body.unit, reference_price=body.reference_price,
        name_i18n=body.name_i18n, spec_items=[i.model_dump() for i in body.spec_items],
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(sku_out(sku, include_cost=True))


@router.put("/{sku_id}", summary="改 SKU(写路径重算 search_text)")
async def update_sku(
    sku_id: int,
    body: SkuUpdateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.CATALOG_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    spec_items = ([i.model_dump() for i in body.spec_items]
                  if body.spec_items is not None else None)
    sku = await sku_service.update_sku(
        db, sku_id=sku_id, name_i18n=body.name_i18n, unit=body.unit,
        reference_price=body.reference_price, spec_items=spec_items,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(sku_out(sku, include_cost=True))


@router.get("/{sku_id}", summary="取 SKU")
async def get_sku(
    sku_id: int,
    current: CurrentUser = Depends(require_permission(Permissions.CATALOG_READ)),
    db: AsyncSession = Depends(get_db),
):
    sku = await sku_service.get_sku(db, sku_id)
    include_cost = Permissions.CATALOG_MANAGE in current.permissions
    return success(sku_out(sku, include_cost=include_cost))


@router.patch("/{sku_id}/status", summary="SKU 上下架")
async def patch_sku_status(
    sku_id: int,
    body: StatusPatchIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.CATALOG_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    sku = await sku_service.set_sku_status(
        db, sku_id=sku_id, status=body.status,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(sku_out(sku, include_cost=True))


@router.delete("/{sku_id}", summary="逻辑删 SKU")
async def delete_sku(
    sku_id: int,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.CATALOG_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    await sku_service.soft_delete_sku(
        db, sku_id=sku_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(None)
