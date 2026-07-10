"""SKU 写服务:模板引导录规格 + 新属性生成稳定键回写模板 + search_text 写路径重算。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import format_code
from app.core.exceptions import NotFoundError, SpecContractError
from app.core.search_text import build_search_text
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.unit import Unit
from app.schemas.sku import validate_spec_items
from app.services import spec_template_service as tmpl
from app.services.numbering import NumberScope, allocate


async def _validate_unit(db: AsyncSession, code: str) -> None:
    """SKU 售卖单位必须 ∈ 现有 units.code 且 is_active(spec §11 Part A)。

    应用层先查后插:干净 404 而非让 FK 违反在 DB 层炸出裸 IntegrityError(镜像
    spu_service._get_leaf_category 对 category_code 的校验写法)。停用单位(仍供
    历史 SKU 引用、FK RESTRICT 保着)不再是新 SKU 的合法选择。
    """
    unit = (await db.execute(
        select(Unit).where(Unit.code == code, Unit.is_active.is_(True))
    )).scalar_one_or_none()
    if unit is None:
        raise NotFoundError(f"售卖单位不存在或已停用: {code}")


async def _resolve_spec(db: AsyncSession, category_code: str, spec_items: list[dict]) -> list[dict]:
    """校验 + 新属性生成稳定键回写模板;返回落库用的 spec_jsonb(仅 key/value)。

    身份≠展示铁律:key 在模板里 → 直接用该 key;不在模板 → 绝不拿用户提交的 key
    (可能是中文原文)直接当 key,而是后端生成独立随机稳定键 `a_<8位 base62>`
    (见 tmpl.create_new_attribute),把用户提交的 label_i18n(zh 必填)落回模板,
    SKU 引用生成键。未知 key 又没带 label_i18n → SpecContractError(新增属性必须带 label_i18n)。
    enum 属性额外校验:填的 value 必须是模板 options 里的 code。

    计量单位归位(spec §11 Part B):单位是属性的固有元数据,只住模板
    category_spec_attributes.unit,spec_jsonb 永不落 unit。用户提交的 `item["unit"]`
    仅在"新增属性"分支被消费,作为该新属性模板行的计量单位录一次(如新增"长度"
    顺手给 unit=mm);对已存在的 key,提交的 unit 一律忽略——不接受某个 SKU 单独
    覆盖模板单位。
    """
    known = await tmpl.suggestions_by_key(db, category_code)
    resolved: list[dict] = []
    for item in spec_items:
        key = item.get("key")
        tmpl_row = known.get(key) if key else None
        if tmpl_row is None:
            label_i18n = item.get("label_i18n")
            if not label_i18n or not label_i18n.get("zh"):
                raise SpecContractError(
                    f"未知属性 key={key!r}:模板中不存在,新增属性须带 label_i18n(zh 必填)")
            tmpl_row = await tmpl.create_new_attribute(
                db, category_code, label_i18n=label_i18n, value_type="string",
                unit=item.get("unit") or None)
            key = tmpl_row["key"]
            known[key] = tmpl_row
        elif tmpl_row.get("value_type") == "enum":
            codes = {opt["code"] for opt in (tmpl_row.get("options") or [])}
            value = item.get("value")
            if not isinstance(value, str) or value not in codes:
                raise SpecContractError(
                    f"属性 '{key}' 的值 {value!r} 不在允许的 enum code 集 {sorted(codes)} 内")
        resolved.append({"key": key, "value": item.get("value")})
    parsed = validate_spec_items(resolved)
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
    sku = (await db.execute(select(Sku).where(
        Sku.id == sku_id, Sku.deleted_at.is_(None)))).scalar_one_or_none()
    if sku is None:
        raise NotFoundError(f"SKU 不存在: {sku_id}")
    return sku


async def search_skus(db: AsyncSession, q: str = "", limit: int = 50, *,
                      spu_id: int | None = None, page: int = 1, size: int | None = None,
                      available: bool = False) -> tuple[list[tuple[Sku, str]], int]:
    """pg_trgm 模糊匹配 search_text(gin_trgm_ops 加速 ILIKE)。

    分页:size 未传时退回 limit(向后兼容旧调用形态)。
    available=True 时派生过滤消费侧「可选货」语义:
    Sku.status=ACTIVE ∧ Sku.deleted_at IS NULL ∧ Spu.status=ACTIVE ∧ Spu.deleted_at IS NULL。
    始终 join spus 带出 main_image,供前端跨 SPU 场景 `sku.image ?? spu.main_image` 回退
    (搜索结果行不像 SPU 详情那样天然带着父 SPU 上下文)。
    返回:list[(Sku, spu_main_image)] + total。
    """
    size = size if size is not None else limit
    conds = [Sku.deleted_at.is_(None)]
    if q and q.strip():
        conds.append(Sku.search_text.ilike(f"%{q.strip()}%"))
    if spu_id is not None:
        conds.append(Sku.spu_id == spu_id)
    if available:
        conds += [Sku.status == "ACTIVE", Spu.status == "ACTIVE", Spu.deleted_at.is_(None)]

    base_from = select(Sku, Spu.main_image).join(Spu, Spu.id == Sku.spu_id).where(*conds)
    count_from = select(func.count()).select_from(Sku).join(Spu, Spu.id == Sku.spu_id).where(*conds)

    total = (await db.execute(count_from)).scalar_one()
    rows = (await db.execute(base_from.order_by(Sku.created_at.desc())
            .offset((page - 1) * size).limit(size))).all()
    return [(r[0], r[1]) for r in rows], total


async def set_sku_status(db: AsyncSession, *, sku_id, status, actor_user_id,
                         actor_user_email, request: Request | None = None) -> Sku:
    sku = await get_sku(db, sku_id)
    sku.status = status
    await write_audit(db, resource_type=AuditResourceType.SKU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=sku.id, request=request, commit=False)
    await db.commit()
    return sku


async def soft_delete_sku(db: AsyncSession, *, sku_id, actor_user_id, actor_user_email,
                          request: Request | None = None) -> None:
    sku = await get_sku(db, sku_id)
    # deleted_at 是 tz-aware DateTime(timezone=True)(SoftDeleteMixin);项目无公共 utcnow
    # 助手(见 spu_service.soft_delete_spu 的同款注释),对齐直取写法。
    sku.deleted_at = datetime.now(timezone.utc)
    await write_audit(db, resource_type=AuditResourceType.SKU, action=AuditAction.DELETE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=sku.id, request=request, commit=False)
    await db.commit()


async def create_sku(db: AsyncSession, *, spu_id, unit, reference_price, name_i18n,
                     spec_items, actor_user_id, actor_user_email,
                     image=None, request: Request | None = None) -> Sku:
    _, category_code = await _spu_category(db, spu_id)
    await _validate_unit(db, unit)
    spec_jsonb = await _resolve_spec(db, category_code, [i for i in spec_items])
    sku_code = format_code(NumberScope.SKU, await allocate(db, NumberScope.SKU))
    sku = Sku(spu_id=spu_id, sku_code=sku_code, unit=unit, reference_price=reference_price,
              spec_jsonb=spec_jsonb, name_i18n=name_i18n, image=image,
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
                     actor_user_email, image=None, request: Request | None = None) -> Sku:
    sku = await get_sku(db, sku_id)
    _, category_code = await _spu_category(db, sku.spu_id)
    if name_i18n is not None:
        sku.name_i18n = name_i18n
    if unit is not None:
        await _validate_unit(db, unit)
        sku.unit = unit
    if reference_price is not None:
        sku.reference_price = reference_price
    if image is not None:
        sku.image = image
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
