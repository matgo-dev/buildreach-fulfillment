"""分类规格属性模板服务:一属性一行(category_spec_attributes),按行 upsert 幂等。

一属性一行(而非分类挂一个 JSONB 数组):DB 层 UNIQUE(category_code,key) 保证唯一;
两个不同 key 的 upsert 各自独立插自己的行,互不覆盖,天然无整包数组读改写(read-
modify-write)的丢更新问题。
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


def _random_option_code() -> str:
    """enum 选项 code:前缀 v_ + 8 位 base62,规矩同 _random_attribute_key(独立随机、
    稳定、非中文、不翻译,secrets 生成)。"""
    return "v_" + "".join(secrets.choice(_KEY_ALPHABET) for _ in range(8))


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

    单行 INSERT ... ON CONFLICT(category_code,key) DO NOTHING + 回读:不同 key 各自一行,
    并发 upsert 不同 key 永远不会互相踩踏丢更新(无需整包数组读改写)。
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


async def add_enum_option(
    db: AsyncSession,
    category_code: str,
    key: str,
    label_i18n: dict,
    *,
    max_retries: int = 5,
) -> str:
    """inline 新增 enum 选项值(运营在录 SKU 时发现现有 options 缺值,如"材质"缺
    "铝合金"):追加进属性行 options JSONB 数组,返回新生成的 code。

    并发坑:options 是属性行上的一整个 JSONB 数组,追加 = read-modify-write
    (CT11 把属性正规化成一属性一行,正是为了躲开这个;但 options 数组本身没法再拆表)。
    这里用 `SELECT ... FOR UPDATE` 锁该属性行:锁住之后再读到的 options 一定是最新的,
    追加完 flush 前锁一直持有,另一并发追加会等到本事务提交后才拿到锁、读到已包含本次
    追加的最新数组,不会互相踩踏丢更新。grain 是单属性、选项数量少、并发概率极低,
    行锁足够,不需要为此再拆一张 options 表。

    code 生成规矩同属性键(_random_attribute_key):独立随机、v_ 前缀、8 位 base62、
    secrets 生成、绝非中文/用户原文的翻译或派生。不按 label 去重——同一属性下选项集
    通常很小,防重复主要靠前端下拉里优先展示已有选项,和属性键一样只认生成 code
    这一个身份维度。
    """
    if not label_i18n.get("zh"):
        raise SpecContractError("label_i18n.zh 必填")
    if any(v in ("", None) for v in label_i18n.values()):
        raise SpecContractError("label_i18n 禁止空串/空值")

    row = (await db.execute(
        select(CategorySpecAttribute)
        .where(CategorySpecAttribute.category_code == category_code, CategorySpecAttribute.key == key)
        .with_for_update()
    )).scalar_one_or_none()
    if row is None:
        raise SpecContractError(f"属性不存在: category_code={category_code!r} key={key!r}")
    if row.value_type != "enum":
        raise SpecContractError(f"属性 '{key}' 非 enum 类型,不支持追加选项")

    existing_codes = {opt["code"] for opt in (row.options or [])}
    for _ in range(max_retries):
        code = _random_option_code()
        if code not in existing_codes:
            break
    else:
        raise SpecContractError("生成选项 code 连续冲突,请重试")

    # 整个新 list 重新赋值(而非原地 .append)——SQLAlchemy 靠属性重赋值侦测变更,
    # 不依赖 MutableList 包装即可正确 UPDATE。
    row.options = [*(row.options or []), {"code": code, "label_i18n": label_i18n}]
    await db.flush()
    return code
