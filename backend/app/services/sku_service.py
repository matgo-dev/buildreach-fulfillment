"""SKU 写服务:模板引导录规格 + 手输 key 回写模板 + search_text 写路径重算。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import format_code
from app.core.exceptions import NotFoundError
from app.core.search_text import build_search_text
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.schemas.sku import validate_spec_items
from app.services import spec_template_service as tmpl
from app.services.numbering import NumberScope, allocate


async def _resolve_spec(db: AsyncSession, category_code: str, spec_items: list[dict]) -> list[dict]:
    """校验 + 手输 key 即时回写模板;返回落库用的 spec_jsonb(key/value/unit)。"""
    known = await tmpl.suggestions_by_key(db, category_code)
    for item in spec_items:
        key = item["key"]
        if key not in known:
            # 手输新 key → 即时 upsert 回模板(source=运营手加),不游离 custom
            await tmpl.upsert_suggestion_key(
                db, category_code, key=key,
                label_i18n=item.get("label_i18n") or {"zh": key},
                value_type="string")
    # 形状/唯一校验(去掉 label_i18n 这个仅回写用的字段)
    stripped = [{k: v for k, v in it.items() if k in ("key", "value", "unit")}
                for it in spec_items]
    parsed = validate_spec_items(stripped)
    return [p.model_dump(exclude_none=True) for p in parsed]


async def _spu_category(db: AsyncSession, spu_id: int) -> tuple[Spu, str]:
    spu = (await db.execute(select(Spu).where(Spu.id == spu_id))).scalar_one_or_none()
    if spu is None:
        raise NotFoundError(f"SPU 不存在: {spu_id}")
    return spu, spu.category_code


async def list_skus_by_spu(db: AsyncSession, spu_id: int) -> list[Sku]:
    return list((await db.execute(select(Sku).where(
        Sku.spu_id == spu_id, Sku.deleted_at.is_(None))
        .order_by(Sku.created_at.desc()))).scalars().all())


def sku_available(sku: Sku, spu: Spu) -> bool:
    """派生可用性(不改字段):SKU 与其所属 SPU 均 ACTIVE 且未删。"""
    return (sku.status == "ACTIVE" and sku.deleted_at is None
            and spu.status == "ACTIVE" and spu.deleted_at is None)


async def spu_ids_with_active_sku(db: AsyncSession, spu_ids: list[int]) -> set[int]:
    """一次分组子查询:给定 SPU id 集合中,哪些至少有一个 ACTIVE 未删 SKU(避免 N+1)。

    仅承载 SKU 侧条件;SPU 自身是否 ACTIVE/未删由调用方另行判断并 AND 之。
    """
    if not spu_ids:
        return set()
    rows = (await db.execute(
        select(Sku.spu_id).where(
            Sku.spu_id.in_(spu_ids), Sku.status == "ACTIVE", Sku.deleted_at.is_(None)
        ).distinct())).scalars().all()
    return set(rows)


async def get_sku(db: AsyncSession, sku_id: int) -> Sku:
    sku = (await db.execute(select(Sku).where(Sku.id == sku_id))).scalar_one_or_none()
    if sku is None:
        raise NotFoundError(f"SKU 不存在: {sku_id}")
    return sku


async def search_skus(db: AsyncSession, q: str, limit: int = 50) -> list[Sku]:
    """pg_trgm 模糊匹配 search_text(gin_trgm_ops 加速 ILIKE)。空 q 返回空。"""
    if not q or not q.strip():
        return []
    pattern = f"%{q.strip()}%"
    rows = (await db.execute(
        select(Sku).where(Sku.search_text.ilike(pattern)).limit(limit))).scalars().all()
    return list(rows)


async def create_sku(db: AsyncSession, *, spu_id, unit, reference_price, name_i18n,
                     spec_items, actor_user_id, actor_user_email,
                     request: Request | None = None) -> Sku:
    _, category_code = await _spu_category(db, spu_id)
    spec_jsonb = await _resolve_spec(db, category_code, [i for i in spec_items])
    sku_code = format_code(NumberScope.SKU, await allocate(db, NumberScope.SKU))
    sku = Sku(spu_id=spu_id, sku_code=sku_code, unit=unit, reference_price=reference_price,
              spec_jsonb=spec_jsonb, name_i18n=name_i18n,
              search_text=build_search_text(name_i18n, spec_jsonb, sku_code))
    db.add(sku)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SKU, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=sku.id, request=request, commit=False)
    await db.commit()
    return sku


async def update_sku(db: AsyncSession, *, sku_id, name_i18n=None, unit=None,
                     reference_price=None, spec_items=None, actor_user_id,
                     actor_user_email, request: Request | None = None) -> Sku:
    sku = (await db.execute(select(Sku).where(Sku.id == sku_id))).scalar_one_or_none()
    if sku is None:
        raise NotFoundError(f"SKU 不存在: {sku_id}")
    _, category_code = await _spu_category(db, sku.spu_id)
    if name_i18n is not None:
        sku.name_i18n = name_i18n
    if unit is not None:
        sku.unit = unit
    if reference_price is not None:
        sku.reference_price = reference_price
    if spec_items is not None:
        sku.spec_jsonb = await _resolve_spec(db, category_code, [i for i in spec_items])
    # 写路径单一入口:任何影响面重算 search_text
    sku.search_text = build_search_text(sku.name_i18n, sku.spec_jsonb, sku.sku_code)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SKU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=sku.id, request=request, commit=False)
    await db.commit()
    return sku
