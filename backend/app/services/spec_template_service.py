"""分类规格属性模板服务:一属性一行(category_spec_attributes),按行 upsert 幂等。

取代旧一分类一行 + JSONB 数组模型(read-modify-write 整个数组丢更新)。
DB 层 UNIQUE(category_code,key) 保证唯一;两个不同 key 的 upsert 各自独立插自己的行,
互不覆盖,从根上消除旧模型的丢更新问题。
"""
from __future__ import annotations

import secrets
import string

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import SpecContractError
from app.db.models.category_spec_attribute import CategorySpecAttribute, SuggestionSource

_KEY_ALPHABET = string.ascii_letters + string.digits


def _random_attribute_key() -> str:
    """独立随机稳定键(前缀 a_ + 8 位 base62)——身份本身随机生成,不是任何 id/计数/
    时间的派生,也绝非用户原文/中文。用 secrets(非 random)保证不可预测。"""
    return "a_" + "".join(secrets.choice(_KEY_ALPHABET) for _ in range(8))


def _to_item(row: CategorySpecAttribute) -> dict:
    return {
        "key": row.key,
        "label_i18n": row.label_i18n,
        "value_type": row.value_type,
        "options": row.options,
        "unit": row.unit,
        "sort_order": row.sort_order,
        "source": row.source,
    }


def _validate_label_and_options(label_i18n: dict, value_type: str, options: list[dict] | None) -> None:
    if not label_i18n.get("zh"):
        raise SpecContractError("label_i18n.zh 必填")
    if any(v in ("", None) for v in label_i18n.values()):
        raise SpecContractError("label_i18n 禁止空串/空值")
    if value_type == "enum" and not options:
        raise SpecContractError("enum 属性必须提供 options")
    if value_type != "enum" and options:
        raise SpecContractError("非 enum 属性不可携带 options")


async def get_suggestions(db: AsyncSession, category_code: str) -> list[dict]:
    rows = (await db.execute(
        select(CategorySpecAttribute)
        .where(CategorySpecAttribute.category_code == category_code)
        .order_by(CategorySpecAttribute.sort_order, CategorySpecAttribute.id)
    )).scalars().all()
    return [_to_item(r) for r in rows]


async def suggestions_by_key(db: AsyncSession, category_code: str) -> dict[str, dict]:
    return {s["key"]: s for s in await get_suggestions(db, category_code)}


async def _next_sort_order(db: AsyncSession, category_code: str) -> int:
    return (await db.execute(
        select(func.coalesce(func.max(CategorySpecAttribute.sort_order), 0) + 10)
        .where(CategorySpecAttribute.category_code == category_code)
    )).scalar_one()


async def upsert_attribute(
    db: AsyncSession,
    category_code: str,
    *,
    key: str,
    label_i18n: dict,
    value_type: str = "string",
    unit: str | None = None,
    options: list[dict] | None = None,
    source: str = SuggestionSource.OPERATOR,
) -> dict:
    """已知 key 的按行幂等 upsert:key 已存在则原样返回不覆盖(保持模板稳定,不因
    重复提交漂移)。调用方须已确定这个 key(种子的人工键,或已在模板中的既有 key)
    ——生成全新随机 key 走 create_new_attribute,不要在这里传一个刚现造的 key。

    单行 INSERT ... ON CONFLICT(category_code,key) DO NOTHING + 回读,取代旧模型
    "整包数组读出来改一条再整包写回去"的 read-modify-write —— 不同 key 各自一行,
    并发 upsert 不同 key 永远不会互相踩踏丢更新。
    """
    _validate_label_and_options(label_i18n, value_type, options)

    next_order = await _next_sort_order(db, category_code)
    stmt = insert(CategorySpecAttribute).values(
        category_code=category_code, key=key, label_i18n=label_i18n,
        value_type=value_type, options=options, unit=unit or "",
        sort_order=next_order, source=source,
    ).on_conflict_do_nothing(index_elements=["category_code", "key"])
    await db.execute(stmt)
    await db.flush()

    row = (await db.execute(select(CategorySpecAttribute).where(
        CategorySpecAttribute.category_code == category_code,
        CategorySpecAttribute.key == key,
    ))).scalar_one()
    return _to_item(row)


async def create_new_attribute(
    db: AsyncSession,
    category_code: str,
    *,
    label_i18n: dict,
    value_type: str = "string",
    unit: str | None = None,
    options: list[dict] | None = None,
    source: str = SuggestionSource.OPERATOR,
    max_retries: int = 5,
) -> dict:
    """运营新增属性:后端生成独立随机稳定键(a_<8位 base62>)并落一行,不接受调用方
    指定 key(禁止把中文/用户原文当 key)。

    插入前生成、一次 INSERT、不回填、不派生自 id —— key 列存的是真身份(独立随机),
    不是内部自增 PK 的派生;别把内部 PK 当外部契约暴露,id 管内部 join,key 管对外引用
    (spec_jsonb 消费端只看得到 key,种子的人工键与这里的随机键一视同仁)。

    唯一性由 UNIQUE(category_code,key) 兜底:INSERT ... ON CONFLICT DO NOTHING
    RETURNING id,极小概率撞键(RETURNING 空)则换个随机键重试,不抛异常不回滚。
    """
    _validate_label_and_options(label_i18n, value_type, options)

    for _ in range(max_retries):
        key = _random_attribute_key()
        next_order = await _next_sort_order(db, category_code)
        stmt = (
            insert(CategorySpecAttribute)
            .values(
                category_code=category_code, key=key, label_i18n=label_i18n,
                value_type=value_type, options=options, unit=unit or "",
                sort_order=next_order, source=source,
            )
            .on_conflict_do_nothing(index_elements=["category_code", "key"])
            .returning(CategorySpecAttribute.id)
        )
        row_id = (await db.execute(stmt)).scalar_one_or_none()
        if row_id is not None:
            await db.flush()
            row = (await db.execute(select(CategorySpecAttribute).where(
                CategorySpecAttribute.id == row_id))).scalar_one()
            return _to_item(row)
        # 撞键(概率 ~1/62^8,几乎不会触发):换个随机键重试

    raise SpecContractError("生成属性 key 连续冲突,请重试")
