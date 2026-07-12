"""SPU 路由 /api/v1/spus。全端点:列表/详情/建/改/上下架/逻辑删。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import require_permission
from app.schemas.common import StatusPatchIn
from app.schemas.spu import SpuCreateIn, SpuOut, SpuUpdateIn
from app.schemas.sku import sku_out
from app.services import image_service, sku_service, spu_service

router = APIRouter(prefix="/spus", tags=["spus"])


@router.get("", summary="SPU 列表")
async def list_spus(
    category_code: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    include_descendants: bool = True,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    _current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_READ)),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await spu_service.list_spus(
        db, category_code=category_code, status=status, keyword=keyword,
        include_descendants=include_descendants, page=page, size=size)
    active_ids = await sku_service.spu_ids_with_active_sku(db, [s.id for s in rows])
    covers = await image_service.cover_keys(db, [s.id for s in rows])
    items = []
    for s in rows:
        d = SpuOut.model_validate(s, from_attributes=True).model_dump()
        d["has_available_sku"] = (
            s.status == "ACTIVE" and s.deleted_at is None and s.id in active_ids)
        d["main_image"] = covers.get(s.id)  # 封面 key(缩略/回退用),无图则 None
        items.append(d)
    return success({"items": items, "total": total, "page": page, "size": size})


@router.get("/{spu_id}", summary="SPU 详情(含内嵌 SKU + 图集 + 派生可用性)")
async def get_spu(
    spu_id: int,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_READ)),
    db: AsyncSession = Depends(get_db),
):
    spu = await spu_service.get_spu(db, spu_id)
    skus = await sku_service.list_skus_by_spu(db, spu_id)
    include_cost = Permissions.PRODUCT_MANAGE in current.permissions
    sku_dicts = []
    for s in skus:
        d = sku_out(s, include_cost=include_cost,
                    images=await image_service.list_sku_images(db, s.id))
        d["available"] = sku_service.sku_available(s, spu)
        sku_dicts.append(d)
    return success({
        **SpuOut.model_validate(spu, from_attributes=True).model_dump(),
        "images": await image_service.list_spu_images(db, spu_id),
        "has_available_sku": any(x["available"] for x in sku_dicts),
        "skus": sku_dicts,
    })


async def _spu_with_images(db: AsyncSession, spu) -> dict:
    return {**SpuOut.model_validate(spu, from_attributes=True).model_dump(),
            "images": await image_service.list_spu_images(db, spu.id)}


@router.post("", summary="建 SPU")
async def create_spu(
    body: SpuCreateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    spu = await spu_service.create_spu(
        db, category_code=body.category_code, name_i18n=body.name_i18n,
        image_refs=[i.model_dump() for i in body.images],
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _spu_with_images(db, spu))


@router.put("/{spu_id}", summary="改 SPU")
async def update_spu(
    spu_id: int,
    body: SpuUpdateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    spu = await spu_service.update_spu(
        db, spu_id=spu_id, name_i18n=body.name_i18n, category_code=body.category_code,
        image_refs=([i.model_dump() for i in body.images] if body.images is not None else None),
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _spu_with_images(db, spu))


@router.patch("/{spu_id}/status", summary="SPU 上下架")
async def patch_spu_status(
    spu_id: int,
    body: StatusPatchIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    spu = await spu_service.set_spu_status(
        db, spu_id=spu_id, status=body.status,
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(SpuOut.model_validate(spu, from_attributes=True).model_dump())


@router.delete("/{spu_id}", summary="逻辑删 SPU")
async def delete_spu(
    spu_id: int,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    await spu_service.soft_delete_spu(
        db, spu_id=spu_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(None)
