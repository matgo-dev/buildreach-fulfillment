"""启动时同步 Role / Permission / RolePermission 到数据库(v3 §10)。

逻辑:
1. 权限点 Permission:**完全镜像**(配置无 → DELETE)
2. 角色 Role:种子角色不存在则插入(不动已有 name/description)
3. RolePermission:完全镜像配置

dry-run 模式:
- 环境变量 PERMISSION_SYNC_MODE=dry_run
- 启动时只输出差异报告,不执行 INSERT/DELETE
- DB 中现有权限数据继续生效,服务正常对外提供请求

约束:
- 作用对象限定 Permission + RolePermission 两表(不触 User/UserRole/Role 数据/业务表)
- 幂等(连续执行 N 次结果一致)
- 输出 [Permission Sync] 标识的差异 + 耗时
"""
from __future__ import annotations

import logging
import os
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.permission import Permission
from app.db.models.role import Role, RoleCode, RoleScope
from app.db.models.role_permission import RolePermission
from app.rbac.constants import PERMISSION_META, ROLE_META
from app.rbac.permissions_config import ROLE_PERMISSIONS

logger = logging.getLogger(__name__)

DRY_RUN_ENV = "PERMISSION_SYNC_MODE"
DRY_RUN_VALUE = "dry_run"


def _is_dry_run() -> bool:
    return os.environ.get(DRY_RUN_ENV, "").lower() == DRY_RUN_VALUE


async def sync_rbac(db: AsyncSession) -> dict:
    """主入口。返回统计字典(便于测试断言)。"""
    started = time.time()
    dry = _is_dry_run()
    if dry:
        logger.warning("[Permission Sync] DRY RUN - no changes will be applied")

    perm_stats = await _sync_permissions(db, dry_run=dry)
    role_stats = await _sync_roles(db, dry_run=dry)
    rp_stats = await _sync_role_permissions(db, dry_run=dry)

    if not dry:
        await db.commit()

    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(
        "[Permission Sync] permissions: +%d / -%d / %d unchanged",
        perm_stats["added"], perm_stats["removed"], perm_stats["unchanged"],
    )
    logger.info(
        "[Permission Sync] role_permissions: +%d / -%d / %d unchanged",
        rp_stats["added"], rp_stats["removed"], rp_stats["unchanged"],
    )
    logger.info("[Permission Sync] done in %dms%s", elapsed_ms, " (dry run)" if dry else "")

    return {
        "dry_run": dry,
        "permissions": perm_stats,
        "roles": role_stats,
        "role_permissions": rp_stats,
        "elapsed_ms": elapsed_ms,
    }


async def _sync_permissions(db: AsyncSession, *, dry_run: bool) -> dict:
    result = await db.execute(select(Permission))
    existing = {p.code: p for p in result.scalars().all()}
    configured_codes = set(PERMISSION_META.keys())

    added = removed = unchanged = updated = 0
    to_add = sorted(configured_codes - existing.keys())
    to_remove = sorted(existing.keys() - configured_codes)

    for code in to_add:
        meta = PERMISSION_META[code]
        if dry_run:
            logger.info("[Permission Sync] would add permission: %s (%s)", code, meta["name"])
        else:
            db.add(Permission(code=code, name=meta["name"], module=meta["module"]))
        added += 1

    for code, perm in existing.items():
        if code not in configured_codes:
            continue
        meta = PERMISSION_META[code]
        if perm.name != meta["name"] or perm.module != meta["module"]:
            if dry_run:
                logger.info("[Permission Sync] would update permission meta: %s", code)
            else:
                perm.name = meta["name"]
                perm.module = meta["module"]
            updated += 1
        else:
            unchanged += 1

    for code in to_remove:
        if dry_run:
            logger.info("[Permission Sync] would remove permission: %s", code)
        else:
            await db.delete(existing[code])
        removed += 1

    if not dry_run:
        await db.flush()
    return {"added": added, "removed": removed, "unchanged": unchanged, "updated": updated}


async def _sync_roles(db: AsyncSession, *, dry_run: bool) -> dict:
    """角色:仅按需 INSERT,不删不改(角色 code 是稳定枚举)。"""
    result = await db.execute(select(Role))
    existing = {r.code: r for r in result.scalars().all()}
    added = 0
    for code in RoleCode.ALL:
        if code in existing:
            continue
        meta = ROLE_META.get(code, {})
        if dry_run:
            logger.info("[Permission Sync] would add role: %s", code)
        else:
            db.add(Role(
                code=code,
                name=meta.get("name", code),
                scope=RoleScope.GLOBAL,
                description=meta.get("description"),
            ))
        added += 1
    if not dry_run:
        await db.flush()
    return {"added": added}


async def _sync_role_permissions(db: AsyncSession, *, dry_run: bool) -> dict:
    """RolePermission:完全镜像配置。"""
    role_result = await db.execute(select(Role))
    roles_by_code = {r.code: r for r in role_result.scalars().all()}

    perm_result = await db.execute(select(Permission))
    perms_by_code = {p.code: p for p in perm_result.scalars().all()}

    rp_result = await db.execute(select(RolePermission))
    existing_rps = list(rp_result.scalars().all())
    existing_pairs: dict[tuple[int, int], RolePermission] = {
        (rp.role_id, rp.permission_id): rp for rp in existing_rps
    }

    desired_pairs: set[tuple[int, int]] = set()
    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        role = roles_by_code.get(role_code)
        if role is None:
            logger.warning("[Permission Sync] role %r not found, skip", role_code)
            continue
        for pcode in perm_codes:
            perm = perms_by_code.get(pcode)
            if perm is None:
                # dry_run 模式 + 即将新增的权限点会落在这里;非 dry_run 上一步已 add
                if dry_run:
                    desired_pairs.add((role.id, -1))  # placeholder
                    logger.info(
                        "[Permission Sync] would add role_permission(待权限点创建后): %s + %s",
                        role_code, pcode,
                    )
                continue
            desired_pairs.add((role.id, perm.id))

    added = removed = 0
    for pair in sorted(desired_pairs - existing_pairs.keys()):
        if pair[1] == -1:
            continue
        if dry_run:
            logger.info("[Permission Sync] would add role_permission: role_id=%s perm_id=%s", *pair)
        else:
            db.add(RolePermission(role_id=pair[0], permission_id=pair[1]))
        added += 1

    for pair in sorted(existing_pairs.keys() - desired_pairs):
        if dry_run:
            logger.info("[Permission Sync] would remove role_permission: role_id=%s perm_id=%s", *pair)
        else:
            await db.delete(existing_pairs[pair])
        removed += 1

    unchanged = len(desired_pairs & existing_pairs.keys())

    if not dry_run:
        await db.flush()
    return {"added": added, "removed": removed, "unchanged": unchanged}
