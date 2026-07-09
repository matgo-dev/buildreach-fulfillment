"""分类规格建议模板服务:读建议 + 手输 key 即时 upsert 回模板(防 key 漂移)。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models.category_spec_suggestion import CategorySpecSuggestion, SuggestionSource


async def _get_row(db: AsyncSession, category_code: str) -> CategorySpecSuggestion | None:
    return (await db.execute(
        select(CategorySpecSuggestion).where(
            CategorySpecSuggestion.category_code == category_code)
    )).scalar_one_or_none()


async def get_suggestions(db: AsyncSession, category_code: str) -> list[dict]:
    row = await _get_row(db, category_code)
    return list(row.suggestions) if row else []


async def suggestions_by_key(db: AsyncSession, category_code: str) -> dict[str, dict]:
    return {s["key"]: s for s in await get_suggestions(db, category_code)}


async def upsert_suggestion_key(
    db: AsyncSession,
    category_code: str,
    *,
    key: str,
    label_i18n: dict,
    value_type: str = "string",
    unit: str | None = None,
) -> dict:
    """手输新 key 即时回写模板(source=运营手加);已存在则原样返回不覆盖。"""
    row = await _get_row(db, category_code)
    if row is None:
        row = CategorySpecSuggestion(category_code=category_code, suggestions=[])
        db.add(row)
        await db.flush()

    for existing in row.suggestions:
        if existing["key"] == key:
            return existing

    next_order = (max((s.get("sort_order", 0) for s in row.suggestions), default=0)) + 10
    item = {
        "key": key,
        "label_i18n": label_i18n,
        "value_type": value_type,
        "unit": unit or "",
        "sort_order": next_order,
        "source": SuggestionSource.OPERATOR,
    }
    row.suggestions = [*row.suggestions, item]
    flag_modified(row, "suggestions")  # JSONB 就地替换需显式标脏
    await db.flush()
    return item
