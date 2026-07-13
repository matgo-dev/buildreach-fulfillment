"""分类只读派生:批量 code→name_i18n(展示用,读响应投影,不落库、非第二源头)。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.category import Category


async def names_by_code(db: AsyncSession, codes: list[str]) -> dict[str, dict]:
    uniq = [c for c in set(codes) if c]
    if not uniq:
        return {}
    rows = (await db.execute(
        select(Category.code, Category.name_i18n).where(Category.code.in_(uniq)))).all()
    return {code: name for code, name in rows}
