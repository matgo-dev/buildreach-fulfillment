"""SKU 路由 /api/v1/skus。M1:加 SKU / 改 SKU(重算 search_text)/ 取 SKU。搜索见 Task 7。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.sku import SkuCreateIn, SkuOut, SkuUpdateIn
from app.services import sku_service

router = APIRouter(prefix="/skus", tags=["skus"])


@router.post("", summary="加 SKU")
async def create_sku(
    body: SkuCreateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.SKU_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    sku = await sku_service.create_sku(
        db, spu_id=body.spu_id, unit=body.unit, reference_price=body.reference_price,
        name_i18n=body.name_i18n, spec_items=[i.model_dump() for i in body.spec_items],
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(SkuOut.model_validate(sku, from_attributes=True).model_dump())


@router.put("/{sku_id}", summary="改 SKU(写路径重算 search_text)")
async def update_sku(
    sku_id: int,
    body: SkuUpdateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.SKU_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    spec_items = ([i.model_dump() for i in body.spec_items]
                  if body.spec_items is not None else None)
    sku = await sku_service.update_sku(
        db, sku_id=sku_id, name_i18n=body.name_i18n, unit=body.unit,
        reference_price=body.reference_price, spec_items=spec_items,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(SkuOut.model_validate(sku, from_attributes=True).model_dump())


@router.get("/{sku_id}", summary="取 SKU")
async def get_sku(
    sku_id: int,
    _current: CurrentUser = Depends(require_permission(Permissions.SKU_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    sku = await sku_service.get_sku(db, sku_id)
    return success(SkuOut.model_validate(sku, from_attributes=True).model_dump())
