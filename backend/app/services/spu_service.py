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
from app.db.models.category import Category
from app.db.models.sku import Sku, SkuStatus
from app.db.models.spu import Spu, SpuStatus
from app.services import image_service
from app.services.numbering import allocate


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


async def _get_leaf_category(db: AsyncSession, code: str) -> Category:
    cat = (await db.execute(select(Category).where(Category.code == code))).scalar_one_or_none()
    if cat is None:
        raise NotFoundError(f"分类不存在: {code}")
    if not cat.is_leaf:
        raise ConflictError(f"商品只能挂叶子分类: {code}")
    return cat


async def get_spu(db: AsyncSession, spu_id: int) -> Spu:
    spu = (await db.execute(
        select(Spu).where(Spu.id == spu_id, Spu.deleted_at.is_(None)))).scalar_one_or_none()
    if spu is None:
        raise NotFoundError(f"SPU 不存在: {spu_id}")
    return spu


async def create_spu(db: AsyncSession, *, category_code, name_i18n, image_refs,
                     actor_user_id, actor_user_email, request: Request | None = None) -> Spu:
    await _get_leaf_category(db, category_code)
    spu_code = format_code(NumberScope.SPU, await allocate(db, NumberScope.SPU))
    spu = Spu(spu_code=spu_code, category_code=category_code, name_i18n=name_i18n,
              created_by=actor_user_id)
    db.add(spu)
    await db.flush()
    await image_service.reconcile_spu_images(db, spu.id, image_refs)
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    return spu


async def update_spu(db: AsyncSession, *, spu_id, name_i18n=None, category_code=None,
                     image_refs=None,
                     actor_user_id, actor_user_email, request: Request | None = None) -> Spu:
    spu = await get_spu(db, spu_id)
    ensure_spu_editable(spu)
    if category_code is not None:
        await _get_leaf_category(db, category_code)
        spu.category_code = category_code
    if name_i18n is not None:
        spu.name_i18n = name_i18n
    removed_keys: list[str] = []
    if image_refs is not None:
        removed_keys = await image_service.reconcile_spu_images(db, spu.id, image_refs)
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    await image_service.gc_orphan_objects(db, removed_keys)  # 提交后回收孤儿存储对象
    return spu


async def set_spu_status(db: AsyncSession, *, spu_id, status, actor_user_id,
                         actor_user_email, request: Request | None = None) -> Spu:
    spu = await get_spu(db, spu_id)
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
    spu = await get_spu(db, spu_id)
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
        # 已知限制:SPU 列表关键词只匹配中文名(name_i18n['zh'])+ spu_code;缺 zh 的记录
        # 静默不匹配。中文运营期足够;多语言上线前再扩(SKU 搜索走 search_text 已覆盖全语言,
        # SPU 无 search_text 去规范化字段,故此处直取 zh)。
        like = f"%{keyword}%"
        conds.append((Spu.name_i18n["zh"].astext.ilike(like)) | (Spu.spu_code.ilike(like)))
    total = (await db.execute(select(func.count()).select_from(Spu).where(*conds))).scalar_one()
    rows = (await db.execute(select(Spu).where(*conds)
            .order_by(Spu.created_at.desc()).offset((page - 1) * size).limit(size))).scalars().all()
    return list(rows), total
