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
from app.services import category_service, image_service, sku_service, spu_service
from app.services import spec_template_service as tmpl

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
    cat_names = await category_service.names_by_code(db, [s.category_code for s in rows])
    items = []
    for s in rows:
        d = SpuOut.model_validate(s, from_attributes=True).model_dump()
        # 完备性告警口径 = 有没有在售 SKU(纯 SKU 状态),与详情「在售 SKU X/共Y」及启用
        # 门禁 has_active_sku 同源。**不叠加 SPU 自身 ACTIVE**——否则草稿 SPU 即便已备好
        # 在售 SKU 也会被误报"无可用",与详情自相矛盾。
        d["has_active_sku"] = s.id in active_ids
        d["main_image"] = covers.get(s.id)  # 封面 key(缩略/回退用),无图则 None
        d["category_name_i18n"] = cat_names.get(s.category_code)
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
    images_by_sku = await image_service.sku_images_by_sku(db, [s.id for s in skus])
    sku_dicts = []
    for s in skus:
        d = sku_out(s, include_cost=include_cost, images=images_by_sku.get(s.id, []))
        d["available"] = sku_service.sku_available(s, spu)
        # SKU 完整规格 = SPU 产品级 ∪ SKU 轴(读时并集,后端单一解析)
        d["spec_display"] = await tmpl.resolve_spec_display(
            db, spu.category_code, list(spu.spec_jsonb or []) + list(s.spec_jsonb or []))
        sku_dicts.append(d)
    # 分类完整路径(根→叶),从 categories 树 parent_code 链派生;叶名取末级,省一次查询。
    cat_path = (await category_service.paths_by_code(db, [spu.category_code])).get(
        spu.category_code, [])
    return success({
        **SpuOut.model_validate(spu, from_attributes=True).model_dump(),
        "category_name_i18n": cat_path[-1]["name_i18n"] if cat_path else None,
        "category_path": cat_path,
        "spec_display": await tmpl.resolve_spec_display(db, spu.category_code, spu.spec_jsonb),
        "images": await image_service.list_spu_images(db, spu_id),
        "has_available_sku": any(x["available"] for x in sku_dicts),
        "skus": sku_dicts,
    })


async def _spu_with_images(db: AsyncSession, spu) -> dict:
    return {**SpuOut.model_validate(spu, from_attributes=True).model_dump(),
            "spec_display": await tmpl.resolve_spec_display(db, spu.category_code, spu.spec_jsonb),
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
        brand=body.brand, description=body.description, hs_code=body.hs_code,
        spec_items=[i.model_dump() for i in body.spec_items],
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
        brand=body.brand, description=body.description, hs_code=body.hs_code,
        spec_items=([i.model_dump() for i in body.spec_items]
                    if body.spec_items is not None else None),
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
