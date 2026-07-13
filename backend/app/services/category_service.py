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


async def paths_by_code(db: AsyncSession, codes: list[str]) -> dict[str, list[dict]]:
    """每个 code → 根→叶完整祖先链 [{code, name_i18n}, ...](含自身)。

    走 parent_code FK 链派生(权威关系,不解析 code 字符串——运营新增分类的 code
    方案未必是点分物化路径)。逐层向上批量取,**不写死层数**(无限上溯到根,加层不炸);
    seen 守卫防脏数据成环。读时投影,不落库、非第二源头。
    """
    leaves = [c for c in set(codes) if c]
    if not leaves:
        return {}
    cache: dict[str, tuple[str | None, dict]] = {}  # code -> (parent_code, name_i18n)
    frontier = set(leaves)
    while frontier:
        rows = (await db.execute(
            select(Category.code, Category.parent_code, Category.name_i18n)
            .where(Category.code.in_(frontier)))).all()
        frontier = {p for _, p, _ in rows if p and p not in cache}
        for code, parent, name in rows:
            cache[code] = (parent, name)
    result: dict[str, list[dict]] = {}
    for leaf in leaves:
        chain, cur, seen = [], leaf, set()
        while cur and cur in cache and cur not in seen:
            seen.add(cur)
            parent, name = cache[cur]
            chain.append({"code": cur, "name_i18n": name})
            cur = parent
        result[leaf] = list(reversed(chain))
    return result
