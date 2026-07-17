"""SPU service。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (ConflictError, IllegalStatusTransitionError, NotFoundError,
                                 ProductIncompleteError, ProductNotEditableError)
from app.core.search_text import build_spu_search_text, build_sku_search_text
from app.db.models.category import Category
from app.db.models.sku import Sku, SkuStatus
from app.db.models.spu import Spu, SpuStatus
from app.services import image_service
from app.services import spec_template_service as tmpl
from app.services.numbering import allocate
from app.services.repo import get_or_404, paginate


def ensure_spu_editable(spu: Spu) -> None:
    """写门禁:SPU 须在 EDITABLE 集(DRAFT/INACTIVE)才可改内容 / 增删其 SKU。

    ACTIVE(启用中,可能正被报价选用)一律拒,先停用再改 —— 状态粒度锁(见 SpuStatus)。
    SKU 侧写操作复用本守卫(sku_service import),单一入口。
    """
    if spu.status not in SpuStatus.EDITABLE:
        raise ProductNotEditableError(
            f"商品当前为 {spu.status}(启用中),不可编辑;请先停用后再改")


async def has_active_sku(db: AsyncSession, spu_id: int) -> bool:
    """启用完备性 / 联动判据:该 SPU 是否至少有一个在售(ACTIVE 未删)SKU。

    只看 status,**不看 reference_price** —— reference_price 是内部采购参考价(红线成本),
    报价成交价由销售另填,报价可选性不依赖它;与消费侧口径(sku_available / search available
    只滤 status=ACTIVE)保持一致(独立 DB 评审 should-fix)。
    """
    n = (await db.execute(select(func.count()).select_from(Sku).where(
        Sku.spu_id == spu_id, Sku.status == SkuStatus.ACTIVE,
        Sku.deleted_at.is_(None)))).scalar_one()
    return n > 0


async def _count_live_skus(db: AsyncSession, spu_id: int) -> int:
    return (await db.execute(select(func.count()).select_from(Sku).where(
        Sku.spu_id == spu_id, Sku.deleted_at.is_(None)))).scalar_one()


async def _spu_search_text(db: AsyncSession, spu: Spu) -> str:
    tmpl_map = await tmpl.suggestions_by_key(db, spu.category_code)
    return build_spu_search_text(
        name_i18n=spu.name_i18n, brand=spu.brand, spec=spu.spec_jsonb,
        spu_code=spu.spu_code, suggestions_by_key=tmpl_map)


async def _recompute_children_search_text(db: AsyncSession, spu: Spu) -> None:
    """SPU 名/品牌/产品级规格变更 → 级联重算所有未软删子 SKU 的 search_text(方案 A)。

    SKU search_text 里 denormalize 了 SPU 名/品牌/规格快照,SPU 改了就旧;SKU 数有限,
    同事务循环重算。含停用(INACTIVE)未删 SKU(默认搜索可返回停用),只排软删。
    """
    tmpl_map = await tmpl.suggestions_by_key(db, spu.category_code)
    skus = (await db.execute(select(Sku).where(
        Sku.spu_id == spu.id, Sku.deleted_at.is_(None)))).scalars().all()
    for sku in skus:
        sku.search_text = build_sku_search_text(
            spu_name_i18n=spu.name_i18n, spu_brand=spu.brand, spu_spec=spu.spec_jsonb,
            sku_name_i18n=sku.name_i18n, sku_spec=sku.spec_jsonb, sku_code=sku.sku_code,
            suggestions_by_key=tmpl_map)
    await db.flush()


async def _get_leaf_category(db: AsyncSession, code: str) -> Category:
    cat = (await db.execute(select(Category).where(Category.code == code))).scalar_one_or_none()
    if cat is None:
        raise NotFoundError(f"分类不存在: {code}")
    if not cat.is_leaf:
        raise ConflictError(f"商品只能挂叶子分类: {code}")
    return cat


async def get_spu(db: AsyncSession, spu_id: int) -> Spu:
    return await get_or_404(db, Spu, spu_id, error_cls=NotFoundError,
                            message=f"SPU 不存在: {spu_id}",
                            extra_where=(Spu.deleted_at.is_(None),))


async def get_spu_for_update(db: AsyncSession, spu_id: int) -> Spu:
    """取 SPU 并对该行加锁(SELECT ... FOR UPDATE)。

    SPU 是商品聚合根:凡"读其 status / 完备性再做决策"的写操作(改 SPU、增删改其 SKU、
    上下架)都经此锁,串行化同一 SPU 的并发写,杜绝 TOCTOU —— 否则两请求并发停售最后
    两个在售 SKU 会各自看不到对方未提交的停售、都不联动下架,留下"ACTIVE 却 0 在售 SKU"
    的坏商品(独立评审 should-fix)。不同 SPU 之间不互斥,锁粒度=单个聚合根行。
    """
    return await get_or_404(db, Spu, spu_id, for_update=True, error_cls=NotFoundError,
                            message=f"SPU 不存在: {spu_id}",
                            extra_where=(Spu.deleted_at.is_(None),))


async def create_spu(db: AsyncSession, *, category_code, name_i18n, image_refs,
                     brand=None, description=None, hs_code=None, spec_items=None,
                     actor_user_id, actor_user_email, request: Request | None = None) -> Spu:
    await _get_leaf_category(db, category_code)
    # 产品级规格(scope='spu'):按品类模板(含继承)解析,落 spus.spec_jsonb。
    spec_jsonb = await tmpl.resolve_spec(
        db, category_code, [i for i in (spec_items or [])], scope="spu")
    spu_code = format_code(NumberScope.SPU, await allocate(db, NumberScope.SPU))
    spu = Spu(spu_code=spu_code, category_code=category_code, name_i18n=name_i18n,
              brand=brand, description=description, hs_code=hs_code, spec_jsonb=spec_jsonb,
              search_text="", created_by=actor_user_id)
    spu.search_text = await _spu_search_text(db, spu)  # 名+品牌+产品级规格(SPU 维度搜索)
    db.add(spu)
    await db.flush()
    await image_service.reconcile_spu_images(db, spu.id, image_refs)
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    return spu


async def update_spu(db: AsyncSession, *, spu_id, name_i18n=None, category_code=None,
                     image_refs=None, brand=None, description=None, hs_code=None, spec_items=None,
                     actor_user_id, actor_user_email, request: Request | None = None) -> Spu:
    spu = await get_spu_for_update(db, spu_id)  # 锁聚合根,串行化并发写
    ensure_spu_editable(spu)
    if category_code is not None and category_code != spu.category_code:
        # 改分类锁:本系统 category=属性 schema 驱动,改分类=改 schema。
        # 有规格或子 SKU 时旧 key 可能不属新类/scope 相反 → 拒绝,先清空规格/删 SKU。
        if spu.spec_jsonb or await _count_live_skus(db, spu.id) > 0:
            raise ConflictError(
                "category_locked: SPU 已有规格或子 SKU,不可改分类;请先清空规格 / 删除 SKU")
        await _get_leaf_category(db, category_code)
        spu.category_code = category_code
    if name_i18n is not None:
        spu.name_i18n = name_i18n
    if brand is not None:
        spu.brand = brand
    if description is not None:
        spu.description = description
    if hs_code is not None:
        spu.hs_code = hs_code
    if spec_items is not None:
        spu.spec_jsonb = await tmpl.resolve_spec(
            db, spu.category_code, [i for i in spec_items], scope="spu")
    # SKU search_text denormalize 了 SPU 名/品牌/规格,这三者(或分类)任一变都要重算:
    # SPU 自身 search_text + 级联所有子 SKU 的 search_text。
    search_stale = any(x is not None for x in (name_i18n, brand, spec_items, category_code))
    removed_keys: list[str] = []
    if image_refs is not None:
        removed_keys = await image_service.reconcile_spu_images(db, spu.id, image_refs)
    if search_stale:
        spu.search_text = await _spu_search_text(db, spu)
        await _recompute_children_search_text(db, spu)  # 名/品牌/规格变→级联重算子 SKU
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    await image_service.gc_orphan_objects(db, removed_keys)  # 提交后回收孤儿存储对象
    return spu


async def set_spu_status(db: AsyncSession, *, spu_id, status, actor_user_id,
                         actor_user_email, request: Request | None = None) -> Spu:
    spu = await get_spu_for_update(db, spu_id)  # 锁聚合根:完备性校验与并发停售 SKU 串行
    # 走转移白名单:启用/停用两向 + 停用后可重启;拒绝 DRAFT↔INACTIVE、同态自转等非法跳。
    if not SpuStatus.can_transition(spu.status, status):
        raise IllegalStatusTransitionError(f"非法状态转移: {spu.status} → {status}")
    # 启用完备性:无在售 SKU 的商品报价选不到货,不许启用(不卡参考价,理由见 has_active_sku)。
    if status == SpuStatus.ACTIVE and not await has_active_sku(db, spu_id):
        raise ProductIncompleteError("启用失败:至少需一个在售 SKU")
    spu.status = status
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    return spu


async def soft_delete_spu(db: AsyncSession, *, spu_id, actor_user_id, actor_user_email,
                          request: Request | None = None) -> None:
    spu = await get_spu_for_update(db, spu_id)  # 锁聚合根
    if spu.status not in SpuStatus.DELETABLE:
        raise ProductNotEditableError(
            f"商品当前为 {spu.status}(启用中),不可删除;请先停用")
    n = (await db.execute(select(func.count()).select_from(Sku).where(
        Sku.spu_id == spu_id, Sku.deleted_at.is_(None)))).scalar_one()
    if n > 0:
        raise ConflictError(f"该 SPU 下还有 {n} 个未删 SKU,请先处理")
    # deleted_at 列为 DateTime(timezone=True)(SoftDeleteMixin),需 tz-aware UTC。
    # 项目未提供公共 utcnow() 助手(app/core/datetime.py 仅有 to_naive_utc,
    # app/db/base.py 的 _utcnow() 是私有且返回 naive,服务于非 tz 列),故此处直取。
    spu.deleted_at = datetime.now(timezone.utc)
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.DELETE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()


async def list_spus(db: AsyncSession, *, category_code=None, status=None, keyword=None,
                    include_descendants: bool = True,
                    page: int = 1, size: int = 20) -> tuple[list[Spu], int]:
    conds = [Spu.deleted_at.is_(None)]
    if category_code:
        if include_descendants:
            # category_code 来自裸查询参数,可能含 LIKE 元字符(%、_),需转义避免误匹配;
            # 结尾 ".%" 是故意的通配符,不转义。
            escaped = (category_code.replace("\\", "\\\\")
                       .replace("%", "\\%").replace("_", "\\_"))
            conds.append(or_(
                Spu.category_code == category_code,
                Spu.category_code.like(f"{escaped}.%", escape="\\"),  # 点分保证 01 不误匹配 010/02
            ))
        else:
            conds.append(Spu.category_code == category_code)
    if status:
        conds.append(Spu.status == status)
    if keyword:
        # SPU 维度搜索走 search_text(名全语言 + 品牌 + 产品级规格,pg_trgm GIN),
        # 让"碳钢/GB-T706/品牌"等产品级词也能搜到商品(方案 A:SPU 找商品、SKU 找变体)。
        conds.append(Spu.search_text.ilike(f"%{keyword}%"))
    return await paginate(
        db, select(Spu).where(*conds).order_by(Spu.created_at.desc()),
        page=page, size=size,
        count_stmt=select(func.count()).select_from(Spu).where(*conds))
