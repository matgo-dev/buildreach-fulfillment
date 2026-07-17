"""SKU 路由 /api/v1/skus。全端点:搜索(分页/派生可用性过滤)/详情/建/改/上下架/逻辑删。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import success
from app.db.session import get_db
from app.rbac.constants import Permissions
from app.rbac.guards import has_permission, require_permission
from app.schemas.common import Page, PageParams, StatusPatchIn
from app.schemas.sku import SkuCreateIn, SkuUpdateIn, sku_out
from app.services import image_service, sku_service, spu_service
from app.services import spec_template_service as tmpl

router = APIRouter(prefix="/skus", tags=["skus"])


@router.get("", summary="搜 SKU(pg_trgm 模糊:名/规格/编码,支持 spu_id/分页/available 过滤)")
async def search_skus(
    page_params: PageParams = Depends(),
    q: str = "",
    spu_id: int | None = None,
    available: bool = Query(False, description="True: 仅返回 SKU/SPU 均 ACTIVE 未删的可选货"),
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_READ)),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await sku_service.search_skus(
        db, q, spu_id=spu_id, page=page_params.page, size=page_params.size,
        available=available)
    include_cost = has_permission(current, Permissions.PRODUCT_MANAGE)
    # 搜索行展示规格 = 只 SKU 轴的展示投影(spec_display),替代裸 spec_jsonb:enum 已翻 label、
    # 带 unit/scope,前端不再各拼各的。模板按分类缓存,一分类一查,避免逐行查模板(N+1)。
    by_key_cache: dict[str, dict] = {}
    items = []
    for sku, spu_main_image, category_code in rows:
        by_key = by_key_cache.get(category_code)
        if by_key is None:
            by_key = await tmpl.suggestions_by_key(db, category_code)
            by_key_cache[category_code] = by_key
        d = sku_out(sku, include_cost=include_cost, spu_main_image=spu_main_image)
        d.pop("spec_jsonb", None)  # 搜索行不下发落库形状,只给展示投影(唯一消费点=搜索页规格列)
        d["spec_display"] = tmpl.project_spec_display(sku.spec_jsonb, by_key)
        items.append(d)
    return success(Page(items=items, total=total,
                        page=page_params.page, size=page_params.size).model_dump())


async def _sku_spec_display(db: AsyncSession, sku) -> list[dict]:
    """SKU 完整规格展示 = SPU 产品级 ∪ SKU 轴(读时并集,后端单一解析)。"""
    spu = await spu_service.get_spu(db, sku.spu_id)  # 活 SKU 必属活 SPU(不变式)
    merged = list(spu.spec_jsonb or []) + list(sku.spec_jsonb or [])
    return await tmpl.resolve_spec_display(db, spu.category_code, merged)


async def _sku_with_images(db: AsyncSession, sku, *, include_cost: bool) -> dict:
    d = sku_out(sku, include_cost=include_cost,
                images=await image_service.list_sku_images(db, sku.id))
    d["spec_display"] = await _sku_spec_display(db, sku)
    return d


@router.post("", summary="加 SKU")
async def create_sku(
    body: SkuCreateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    sku = await sku_service.create_sku(
        db, spu_id=body.spu_id, unit=body.unit, reference_price=body.reference_price,
        name_i18n=body.name_i18n, spec_items=[i.model_dump() for i in body.spec_items],
        weight_kg=body.weight_kg, length_cm=body.length_cm,
        width_cm=body.width_cm, height_cm=body.height_cm,
        image_refs=[i.model_dump() for i in body.images],
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _sku_with_images(db, sku, include_cost=True))


@router.put("/{sku_id}", summary="改 SKU(写路径重算 search_text)")
async def update_sku(
    sku_id: int,
    body: SkuUpdateIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    spec_items = ([i.model_dump() for i in body.spec_items]
                  if body.spec_items is not None else None)
    sku = await sku_service.update_sku(
        db, sku_id=sku_id, name_i18n=body.name_i18n, unit=body.unit,
        reference_price=body.reference_price, spec_items=spec_items,
        weight_kg=body.weight_kg, length_cm=body.length_cm,
        width_cm=body.width_cm, height_cm=body.height_cm,
        image_refs=([i.model_dump() for i in body.images] if body.images is not None else None),
        actor_user_id=current.id, actor_user_email=current.email, request=request)
    return success(await _sku_with_images(db, sku, include_cost=True))


@router.get("/{sku_id}", summary="取 SKU")
async def get_sku(
    sku_id: int,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_READ)),
    db: AsyncSession = Depends(get_db),
):
    sku = await sku_service.get_sku(db, sku_id)
    include_cost = has_permission(current, Permissions.PRODUCT_MANAGE)
    return success(await _sku_with_images(db, sku, include_cost=include_cost))


@router.patch("/{sku_id}/status", summary="SKU 上下架")
async def patch_sku_status(
    sku_id: int,
    body: StatusPatchIn,
    request: Request,
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
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
    current: CurrentUser = Depends(require_permission(Permissions.PRODUCT_MANAGE)),
    db: AsyncSession = Depends(get_db),
):
    await sku_service.soft_delete_sku(
        db, sku_id=sku_id, actor_user_id=current.id, actor_user_email=current.email,
        request=request)
    return success(None)
