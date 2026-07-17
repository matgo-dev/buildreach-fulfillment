"""SKU 写服务:模板引导录规格 + 新属性生成稳定键回写模板 + search_text 写路径重算。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import NotFoundError
from app.core.search_text import build_sku_search_text
from app.db.models.sku import Sku, SkuStatus
from app.db.models.spu import Spu, SpuStatus
from app.db.models.unit import Unit
from app.services import image_service
from app.services import spec_template_service as tmpl
from app.services.numbering import allocate
from app.services.repo import get_or_404, paginate
from app.services.spu_service import ensure_spu_editable, get_spu_for_update, has_active_sku


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


async def _sku_search_text(db: AsyncSession, spu: Spu, sku: Sku) -> str:
    """SKU search_text = SPU 名+品牌+产品级规格 ∪ SKU 名+轴规格 + sku_code(方案 A)。

    denormalize SPU 上下文进 SKU,故搜 SPU 名/材质/标准都能命中该 SKU(报价等 SKU 级操作)。
    enum 值解析成 label 入索引,搜中文材质词也命中。SPU 名/品牌/规格变→级联重算(见 spu_service)。
    """
    tmpl_map = await tmpl.suggestions_by_key(db, spu.category_code)
    return build_sku_search_text(
        spu_name_i18n=spu.name_i18n, spu_brand=spu.brand, spu_spec=spu.spec_jsonb,
        sku_name_i18n=sku.name_i18n, sku_spec=sku.spec_jsonb, sku_code=sku.sku_code,
        suggestions_by_key=tmpl_map)


async def _spu_category(db: AsyncSession, spu_id: int) -> tuple[Spu, str]:
    # 必须滤软删:否则可对已删 SPU 挂新 SKU(孤儿——SKU 可搜可读而父 SPU 404),
    # 与 get_spu 同款不变式(活 SKU 必属活 SPU)。
    # 锁父 SPU 聚合根(FOR UPDATE):SKU 增改删的 editable 判定与并发 set_spu_status
    # 串行,防 TOCTOU —— 直接复用 spu_service.get_spu_for_update(同查询同锁同报错)。
    # 此函数仅写路径调用。
    spu = await get_spu_for_update(db, spu_id)
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
    return await get_or_404(db, Sku, sku_id, error_cls=NotFoundError,
                            message=f"SKU 不存在: {sku_id}",
                            extra_where=(Sku.deleted_at.is_(None),))


async def search_skus(db: AsyncSession, q: str = "", limit: int = 50, *,
                      spu_id: int | None = None, page: int = 1, size: int | None = None,
                      available: bool = False) -> tuple[list[tuple[Sku, str, str]], int]:
    """pg_trgm 模糊匹配 search_text(gin_trgm_ops 加速 ILIKE)。

    分页:size 未传时退回 limit(向后兼容旧调用形态)。
    available=True 时派生过滤消费侧「可选货」语义:
    Sku.status=ACTIVE ∧ Sku.deleted_at IS NULL ∧ Spu.status=ACTIVE ∧ Spu.deleted_at IS NULL。
    带出所属 SPU 封面(product_images 的 SPU 级 MAIN,批量 cover_keys 避免 N+1),供前端跨 SPU
    场景 `SKU 首图 ?? spu_main_image` 回退(搜索结果行不像 SPU 详情那样天然带父 SPU 上下文)。
    同时带出每行所属 SPU 的 category_code(批量,避免 N+1),供路由按分类缓存模板批量投影
    spec_display。返回:list[(Sku, spu_main_image, category_code)] + total。
    """
    size = size if size is not None else limit
    conds = [Sku.deleted_at.is_(None)]
    if q and q.strip():
        conds.append(Sku.search_text.ilike(f"%{q.strip()}%"))
    if spu_id is not None:
        conds.append(Sku.spu_id == spu_id)
    if available:
        conds += [Sku.status == "ACTIVE", Spu.status == "ACTIVE", Spu.deleted_at.is_(None)]

    base_from = select(Sku).join(Spu, Spu.id == Sku.spu_id).where(*conds)
    count_from = select(func.count()).select_from(Sku).join(Spu, Spu.id == Sku.spu_id).where(*conds)

    rows, total = await paginate(
        db, base_from.order_by(Sku.created_at.desc()),
        page=page, size=size, count_stmt=count_from)
    covers = await image_service.cover_keys(db, [s.spu_id for s in rows])
    spu_ids = list({s.spu_id for s in rows})
    cat_by_spu = dict((await db.execute(
        select(Spu.id, Spu.category_code).where(Spu.id.in_(spu_ids)))).all()) if spu_ids else {}
    return [(s, covers.get(s.spu_id), cat_by_spu.get(s.spu_id)) for s in rows], total


async def set_sku_status(db: AsyncSession, *, sku_id, status, actor_user_id,
                         actor_user_email, request: Request | None = None) -> Sku:
    """SKU 上下架 —— **豁免**父 SPU EDITABLE 锁:启用中的商品下也允许停售单个缺货变体。

    联动(保 ACTIVE⇒有在售 SKU 不变式):停用后若父 SPU 仍 ACTIVE 但已无在售 SKU,
    自动把 SPU 一并下架(INACTIVE),否则会留一个"启用却选不出可报价 SKU"的坏商品。
    """
    sku = await get_sku(db, sku_id)
    # 先锁父 SPU 聚合根,串行化完备性判定 —— 防两请求并发停售各自漏联动、
    # 留下 ACTIVE 却 0 在售 SKU 的坏商品(见 spu_service.get_spu_for_update)。
    spu = (await db.execute(select(Spu).where(
        Spu.id == sku.spu_id, Spu.deleted_at.is_(None)).with_for_update())).scalar_one_or_none()
    sku.status = status
    await db.flush()  # 让下方完备性查询看到本次停用结果
    if (status == SkuStatus.INACTIVE and spu is not None
            and spu.status == SpuStatus.ACTIVE and not await has_active_sku(db, sku.spu_id)):
        spu.status = SpuStatus.INACTIVE  # 联动下架,保 ACTIVE⇒有在售 SKU 不变式
        await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.UPDATE,
                          user_id=actor_user_id, user_email=actor_user_email,
                          resource_id=spu.id, request=request, commit=False)
    await write_audit(db, resource_type=AuditResourceType.SKU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=sku.id, request=request, commit=False)
    await db.commit()
    return sku


async def soft_delete_sku(db: AsyncSession, *, sku_id, actor_user_id, actor_user_email,
                          request: Request | None = None) -> None:
    sku = await get_sku(db, sku_id)
    spu, _ = await _spu_category(db, sku.spu_id)
    ensure_spu_editable(spu)  # 父 SPU 启用中不可删 SKU,先停用(停售单个变体走 set_sku_status)
    # deleted_at 是 tz-aware DateTime(timezone=True)(SoftDeleteMixin);项目无公共 utcnow
    # 助手(见 spu_service.soft_delete_spu 的同款注释),对齐直取写法。
    sku.deleted_at = datetime.now(timezone.utc)
    await write_audit(db, resource_type=AuditResourceType.SKU, action=AuditAction.DELETE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=sku.id, request=request, commit=False)
    await db.commit()


async def create_sku(db: AsyncSession, *, spu_id, unit, reference_price, name_i18n,
                     spec_items, weight_kg=None, length_cm=None, width_cm=None, height_cm=None,
                     actor_user_id, actor_user_email,
                     image_refs=None, request: Request | None = None) -> Sku:
    spu, category_code = await _spu_category(db, spu_id)
    ensure_spu_editable(spu)  # 父 SPU 启用中不可加 SKU,先停用
    await _validate_unit(db, unit)
    spec_jsonb = await tmpl.resolve_spec(db, category_code, [i for i in spec_items], scope="sku")
    sku_code = format_code(NumberScope.SKU, await allocate(db, NumberScope.SKU))
    sku = Sku(spu_id=spu_id, sku_code=sku_code, unit=unit, reference_price=reference_price,
              spec_jsonb=spec_jsonb, name_i18n=name_i18n,
              weight_kg=weight_kg, length_cm=length_cm, width_cm=width_cm, height_cm=height_cm,
              search_text="", created_by=actor_user_id)
    sku.search_text = await _sku_search_text(db, spu, sku)  # 名 + (SPU∪SKU)规格 + code
    db.add(sku)
    await db.flush()
    await image_service.reconcile_sku_images(db, spu_id, sku.id, image_refs or [])
    await write_audit(db, resource_type=AuditResourceType.SKU, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=sku.id, request=request, commit=False)
    await db.commit()
    return sku


async def update_sku(db: AsyncSession, *, sku_id, name_i18n=None, unit=None,
                     reference_price=None, spec_items=None,
                     weight_kg=None, length_cm=None, width_cm=None, height_cm=None,
                     actor_user_id,
                     actor_user_email, image_refs=None, request: Request | None = None) -> Sku:
    sku = await get_sku(db, sku_id)
    spu, category_code = await _spu_category(db, sku.spu_id)
    ensure_spu_editable(spu)  # 父 SPU 启用中不可改 SKU,先停用
    if name_i18n is not None:
        sku.name_i18n = name_i18n
    if unit is not None:
        await _validate_unit(db, unit)
        sku.unit = unit
    if reference_price is not None:
        sku.reference_price = reference_price
    if weight_kg is not None:
        sku.weight_kg = weight_kg
    if length_cm is not None:
        sku.length_cm = length_cm
    if width_cm is not None:
        sku.width_cm = width_cm
    if height_cm is not None:
        sku.height_cm = height_cm
    removed_keys: list[str] = []
    if image_refs is not None:
        removed_keys = await image_service.reconcile_sku_images(db, sku.spu_id, sku.id, image_refs)
    if spec_items is not None:
        sku.spec_jsonb = await tmpl.resolve_spec(
            db, category_code, [i for i in spec_items], scope="sku")
    # 写路径单一入口:任何影响面重算 search_text(名/规格改了都要),用 SPU∪SKU 并集
    sku.search_text = await _sku_search_text(db, spu, sku)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SKU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=sku.id, request=request, commit=False)
    await db.commit()
    await image_service.gc_orphan_objects(db, removed_keys)  # 提交后回收孤儿存储对象
    return sku
