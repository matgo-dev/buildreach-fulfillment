"""分类服务:树形主数据维护 + 读投影。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.category import Category


def _to_out(c: Category) -> dict:
    return {
        "id": c.id,
        "code": c.code,
        "parent_code": c.parent_code,
        "name_i18n": c.name_i18n,
        "level": c.level,
        "is_leaf": c.is_leaf,
        "is_active": c.is_active,
        "sort_order": c.sort_order,
        "updated_at": c.updated_at,
    }


async def get_category(db: AsyncSession, code: str, *, for_update: bool = False) -> Category:
    stmt = select(Category).where(Category.code == code)
    if for_update:
        stmt = stmt.with_for_update()
    c = (await db.execute(stmt)).scalar_one_or_none()
    if c is None:
        raise NotFoundError(f"分类不存在: {code}")
    return c


async def list_tree(db: AsyncSession, *, include_inactive: bool = False) -> list[dict]:
    conds = [] if include_inactive else [Category.is_active.is_(True)]
    rows = (await db.execute(
        select(Category).where(*conds).order_by(Category.level, Category.sort_order, Category.code)
    )).scalars().all()
    return [_to_out(c) for c in rows]


async def create_category(db: AsyncSession, *, code: str, parent_code: str | None,
                          name_i18n: dict, sort_order: int,
                          actor_user_id: int, actor_user_email: str,
                          request: Request | None = None) -> Category:
    exists = (await db.execute(
        select(Category.id).where(Category.code == code))).scalar_one_or_none()
    if exists is not None:
        raise ConflictError(f"分类编码已存在: {code}")

    parent: Category | None = None
    level = 1
    if parent_code:
        parent = await get_category(db, parent_code, for_update=True)
        if not parent.is_active:
            raise ConflictError(f"父分类已停用,请先启用父分类: {parent_code}")
        level = parent.level + 1

    c = Category(code=code, parent_code=parent_code, name_i18n=name_i18n, level=level,
                 is_leaf=True, is_active=True, sort_order=sort_order)
    db.add(c)
    if parent is not None and parent.is_leaf:
        parent.is_leaf = False
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.CATEGORY, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=c.id, request=request, commit=False)
    await db.commit()
    await db.refresh(c)
    return c


async def update_category(db: AsyncSession, *, code: str, name_i18n: dict, sort_order: int,
                          actor_user_id: int, actor_user_email: str,
                          request: Request | None = None) -> Category:
    c = await get_category(db, code, for_update=True)
    c.name_i18n = name_i18n
    c.sort_order = sort_order
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.CATEGORY, action=AuditAction.UPDATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=c.id, request=request, commit=False)
    await db.commit()
    await db.refresh(c)
    return c


async def _descendant_codes(db: AsyncSession, code: str) -> list[str]:
    """按 parent_code 链取子树 code。分类层级有限,用逐层批量查,不解析点分 code。"""
    result = [code]
    frontier = [code]
    while frontier:
        children = list((await db.execute(
            select(Category.code).where(Category.parent_code.in_(frontier))
        )).scalars().all())
        result.extend(children)
        frontier = children
    return result


async def _ancestor_codes(db: AsyncSession, code: str) -> list[str]:
    result: list[str] = []
    cur = await get_category(db, code)
    parent_code = cur.parent_code
    seen = {code}
    while parent_code and parent_code not in seen:
        seen.add(parent_code)
        parent = await get_category(db, parent_code)
        result.append(parent.code)
        parent_code = parent.parent_code
    return result


async def deactivate_category(db: AsyncSession, *, code: str, actor_user_id: int,
                              actor_user_email: str,
                              request: Request | None = None) -> Category:
    c = await get_category(db, code, for_update=True)
    codes = await _descendant_codes(db, code)
    rows = (await db.execute(
        select(Category).where(Category.code.in_(codes)).with_for_update()
    )).scalars().all()
    for row in rows:
        row.is_active = False
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.CATEGORY, action=AuditAction.DEACTIVATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=c.id, request=request, commit=False)
    await db.commit()
    await db.refresh(c)
    return c


async def activate_category(db: AsyncSession, *, code: str, actor_user_id: int,
                            actor_user_email: str,
                            request: Request | None = None) -> Category:
    c = await get_category(db, code, for_update=True)
    codes = [code, *await _ancestor_codes(db, code)]
    rows = (await db.execute(
        select(Category).where(Category.code.in_(codes)).with_for_update()
    )).scalars().all()
    for row in rows:
        row.is_active = True
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.CATEGORY, action=AuditAction.ACTIVATE,
                      user_id=actor_user_id, user_email=actor_user_email,
                      resource_id=c.id, request=request, commit=False)
    await db.commit()
    await db.refresh(c)
    return c

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
