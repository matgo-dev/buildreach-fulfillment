"""分类服务:树形主数据维护 + 读投影。"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.db.models.category import Category

_MAX_CATEGORY_LEVEL = 4
_CATEGORY_CODE_RE = re.compile(r"^(?!00(?:\.|$))\d{2}(?:\.(?!000)\d{3}){0,3}$")
_CATEGORY_CODE_MESSAGE = "分类编码格式应为 01 / 01.001 / 01.001.003 / 01.001.003.001"


def _normalize_category_code(code: str, *, field: str = "code") -> str:
    normalized = code.strip()
    if not _CATEGORY_CODE_RE.fullmatch(normalized):
        raise ValidationFailedError(f"{field}: {_CATEGORY_CODE_MESSAGE}")
    return normalized


def _normalize_category_code_opt(code: str | None, *, field: str = "parent_code") -> str | None:
    if code is None:
        return None
    normalized = code.strip()
    if not normalized:
        return None
    return _normalize_category_code(normalized, field=field)


def _code_level(code: str) -> int:
    return code.count(".") + 1


def _assert_create_parentage(*, code: str, parent_code: str | None) -> None:
    level = _code_level(code)
    if parent_code is None:
        if level != 1:
            raise ValidationFailedError("根分类编码必须是一段,例如 01")
        return

    parent_level = _code_level(parent_code)
    if parent_level >= _MAX_CATEGORY_LEVEL:
        raise ValidationFailedError("分类最多支持四级")
    if level != parent_level + 1 or not code.startswith(f"{parent_code}."):
        raise ValidationFailedError("子分类编码必须在父级编码后追加一段三位数字")


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
    code = _normalize_category_code(code)
    stmt = select(Category).where(Category.code == code)
    if for_update:
        stmt = stmt.with_for_update()
    c = (await db.execute(stmt)).scalar_one_or_none()
    if c is None:
        raise NotFoundError(f"分类不存在: {code}")
    return c


async def _ancestor_chain(db: AsyncSession, code: str, *, for_update: bool = False) -> list[Category]:
    """返回根→当前节点链。for_update=True 时按根→叶顺序锁,供写入路径消除死锁环。"""
    chain: list[Category] = []
    cur = await get_category(db, code)
    seen: set[str] = set()
    while cur.code not in seen:
        seen.add(cur.code)
        chain.append(cur)
        if not cur.parent_code:
            break
        cur = await get_category(db, cur.parent_code)

    codes = [c.code for c in reversed(chain)]
    if not for_update:
        return list(reversed(chain))

    rows = (await db.execute(
        select(Category)
        .where(Category.code.in_(codes))
        .order_by(Category.level, Category.code)
        .with_for_update()
        .execution_options(populate_existing=True)
    )).scalars().all()
    by_code = {row.code: row for row in rows}
    return [by_code[c] for c in codes]


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
    code = _normalize_category_code(code)
    parent_code = _normalize_category_code_opt(parent_code)
    _assert_create_parentage(code=code, parent_code=parent_code)

    exists = (await db.execute(
        select(Category.id).where(Category.code == code))).scalar_one_or_none()
    if exists is not None:
        raise ConflictError(f"分类编码已存在: {code}")

    parent: Category | None = None
    level = _code_level(code)
    if parent_code:
        chain = await _ancestor_chain(db, parent_code, for_update=True)
        parent = chain[-1]
        inactive = next((c for c in chain if not c.is_active), None)
        if inactive is not None:
            raise ConflictError(f"上级分类已停用,请先启用分类: {inactive.code}")
        if parent.level >= _MAX_CATEGORY_LEVEL:
            raise ValidationFailedError("分类最多支持四级")
        if level != parent.level + 1:
            raise ValidationFailedError("分类编码层级必须与父级一致")

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

    走 parent_code FK 链派生(权威关系,不解析 code 字符串)。逐层向上批量取,
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
