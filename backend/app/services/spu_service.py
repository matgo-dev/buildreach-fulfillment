"""SPU service。"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.category import Category
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.services.numbering import allocate


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


async def create_spu(db: AsyncSession, *, category_code, name_i18n, main_image, images=None,
                     actor_user_id, actor_user_email, request: Request | None = None) -> Spu:
    await _get_leaf_category(db, category_code)
    spu_code = format_code(NumberScope.SPU, await allocate(db, NumberScope.SPU))
    spu = Spu(spu_code=spu_code, category_code=category_code, name_i18n=name_i18n,
              main_image=main_image, images=images if images is not None else [],
              created_by=actor_user_id)
    db.add(spu)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    return spu


async def update_spu(db: AsyncSession, *, spu_id, name_i18n=None, category_code=None,
                     main_image=None, images=None,
                     actor_user_id, actor_user_email, request: Request | None = None) -> Spu:
    spu = await get_spu(db, spu_id)
    if category_code is not None:
        await _get_leaf_category(db, category_code)
        spu.category_code = category_code
    if name_i18n is not None:
        spu.name_i18n = name_i18n
    if main_image is not None:
        spu.main_image = main_image
    if images is not None:
        spu.images = images
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    return spu


async def set_spu_status(db: AsyncSession, *, spu_id, status, actor_user_id,
                         actor_user_email, request: Request | None = None) -> Spu:
    spu = await get_spu(db, spu_id)
    spu.status = status
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    return spu


async def soft_delete_spu(db: AsyncSession, *, spu_id, actor_user_id, actor_user_email,
                          request: Request | None = None) -> None:
    spu = await get_spu(db, spu_id)
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
