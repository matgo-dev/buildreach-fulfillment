"""SPU service。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import format_code
from app.core.exceptions import NotFoundError
from app.db.models.category import Category
from app.db.models.spu import Spu
from app.services.numbering import NumberScope, allocate


async def create_spu(db: AsyncSession, *, category_code, name_i18n, actor_user_id,
                     actor_user_email, request: Request | None = None) -> Spu:
    cat = (await db.execute(
        select(Category).where(Category.code == category_code))).scalar_one_or_none()
    if cat is None:
        raise NotFoundError(f"分类不存在: {category_code}")
    spu_code = format_code(NumberScope.SPU, await allocate(db, NumberScope.SPU))
    spu = Spu(spu_code=spu_code, category_code=category_code, name_i18n=name_i18n)
    db.add(spu)
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.SPU, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=spu.id, request=request, commit=False)
    await db.commit()
    return spu
