"""角色权限矩阵 service(只读)。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.permission import Permission
from app.db.models.role import Role, RoleCode
from app.db.models.role_permission import RolePermission


async def list_roles_with_permissions(db: AsyncSession) -> list[dict]:
    """角色 → 权限点矩阵。单一源头查 DB(roles/role_permissions/permissions,由
    rbac/sync.py 启动时从 permissions_config.py 镜像而来),不重复解读配置文件。"""
    stmt = (
        select(Role, Permission)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .order_by(Role.id, Permission.module, Permission.code)
    )
    rows = (await db.execute(stmt)).all()

    by_role: dict[str, dict] = {}
    for role, perm in rows:
        entry = by_role.setdefault(
            role.code,
            {"code": role.code, "name": role.name, "description": role.description, "permissions": []},
        )
        entry["permissions"].append({"code": perm.code, "name": perm.name, "module": perm.module})

    # 角色是稳定枚举(非用户可配置数据),按 RoleCode.ALL 固定顺序输出
    return [by_role[code] for code in RoleCode.ALL if code in by_role]
