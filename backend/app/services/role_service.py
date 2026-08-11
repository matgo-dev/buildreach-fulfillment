"""角色权限 service。

系统内置角色由代码配置维护;自定义角色仅允许配置只读权限,用于股东/审阅/外部
只读账号这类不确定组合。自定义角色复用 roles / role_permissions 表,不引入新表。
"""
from __future__ import annotations

import re

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.db.models.permission import Permission
from app.db.models.role import Role, RoleCode
from app.db.models.role_permission import RolePermission
from app.db.models.user_role import UserRole
from app.rbac.constants import Permissions

SYSTEM_ROLE_CODES = set(RoleCode.ALL)

_ROLE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,49}$")
_AUTH_BASE = frozenset({
    Permissions.AUTH_LOGIN,
    Permissions.AUTH_LOGOUT,
    Permissions.AUTH_ME,
})

# 自定义角色第一版只做只读能力。purchase:read_cost 是采购成本可见性开关,语义为读。
ASSIGNABLE_READ_PERMISSIONS = frozenset({
    Permissions.CUSTOMER_READ,
    Permissions.PRODUCT_READ,
    Permissions.SALES_READ,
    Permissions.SUPPLIER_READ,
    Permissions.PURCHASE_READ,
    Permissions.PURCHASE_READ_COST,
    Permissions.INBOUND_READ,
    Permissions.PAYABLE_READ,
    Permissions.INVENTORY_READ,
    Permissions.OUTBOUND_READ,
    Permissions.SHIPMENT_READ,
    Permissions.RECEIVABLE_READ,
    Permissions.RECEIPT_READ,
    Permissions.PAYMENT_READ,
})
CUSTOM_READONLY_ALLOWED_PERMISSIONS = _AUTH_BASE | ASSIGNABLE_READ_PERMISSIONS


def is_system_role(code: str) -> bool:
    return code in SYSTEM_ROLE_CODES


def _is_custom_readonly_permission_set(role_code: str, permission_codes: set[str]) -> bool:
    if is_system_role(role_code):
        return False
    business_read_codes = permission_codes - _AUTH_BASE
    return bool(business_read_codes) and permission_codes <= CUSTOM_READONLY_ALLOWED_PERMISSIONS


def _role_sort_key(code: str) -> tuple[int, str]:
    if code in RoleCode.ALL:
        return (0, f"{RoleCode.ALL.index(code):03d}")
    return (1, code)


def _build_role(role: Role, permissions: list[Permission]) -> dict:
    permission_codes = {p.code for p in permissions}
    return {
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_system": is_system_role(role.code),
        "is_custom_readonly": _is_custom_readonly_permission_set(role.code, permission_codes),
        "permissions": [
            {"code": p.code, "name": p.name, "module": p.module}
            for p in sorted(permissions, key=lambda p: (p.module, p.code))
        ],
    }


async def list_roles_with_permissions(db: AsyncSession) -> list[dict]:
    """角色 → 权限点矩阵。

    系统角色按 RoleCode.ALL 排序,自定义角色按 code 排序。权限点从 DB 查,让后台新建
    自定义角色后无需改前端静态枚举即可出现在矩阵与用户角色下拉中。
    """
    stmt = (
        select(Role, Permission)
        .select_from(Role)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .order_by(Role.id, Permission.module, Permission.code)
    )
    rows = (await db.execute(stmt)).all()

    by_role: dict[str, tuple[Role, list[Permission]]] = {}
    for role, perm in rows:
        _, perms = by_role.setdefault(role.code, (role, []))
        perms.append(perm)

    return [
        _build_role(role, perms)
        for _, (role, perms) in sorted(by_role.items(), key=lambda item: _role_sort_key(item[0]))
    ]


async def list_assignable_permissions(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(
        select(Permission)
        .where(Permission.code.in_(ASSIGNABLE_READ_PERMISSIONS))
        .order_by(Permission.module, Permission.code)
    )).scalars().all()
    return [{"code": p.code, "name": p.name, "module": p.module} for p in rows]


def _normalize_role_code(code: str) -> str:
    normalized = code.strip().upper()
    if not _ROLE_CODE_RE.fullmatch(normalized):
        raise ValidationFailedError("角色 code 必须是 2-50 位大写字母/数字/下划线,且以字母开头")
    if normalized in SYSTEM_ROLE_CODES:
        raise ValidationFailedError("系统内置角色不可作为自定义角色 code")
    return normalized


def _normalize_permission_codes(permission_codes: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in permission_codes:
        code = raw.strip()
        if not code or code in _AUTH_BASE:
            continue
        if code not in normalized:
            normalized.append(code)
    if not normalized:
        raise ValidationFailedError("自定义角色至少选择一个只读权限")
    invalid = sorted(set(normalized) - ASSIGNABLE_READ_PERMISSIONS)
    if invalid:
        raise ValidationFailedError(f"自定义角色只能选择只读权限,非法权限: {invalid}")
    return normalized


async def _load_permissions(db: AsyncSession, permission_codes: list[str]) -> dict[str, Permission]:
    all_codes = sorted(set(permission_codes) | set(_AUTH_BASE))
    rows = (await db.execute(select(Permission).where(Permission.code.in_(all_codes)))).scalars().all()
    by_code = {p.code: p for p in rows}
    missing = sorted(set(all_codes) - by_code.keys())
    if missing:
        raise NotFoundError(f"权限点不存在: {missing}")
    return by_code


async def _load_role_permission_codes(db: AsyncSession, role_id: int) -> list[str]:
    rows = (await db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.code)
    )).all()
    return [code for (code,) in rows]


def _ensure_custom_readonly_role(role: Role, permission_codes: list[str]) -> None:
    if is_system_role(role.code):
        raise ValidationFailedError("系统内置角色不可编辑")
    if not _is_custom_readonly_permission_set(role.code, set(permission_codes)):
        raise ValidationFailedError("非内置角色必须是自定义只读角色才可通过此接口管理")


async def validate_assignable_roles(db: AsyncSession, roles_by_code: dict[str, Role]) -> None:
    """用户分配角色守卫。

    内置角色由代码维护;非内置角色必须以当前 DB 权限集合证明自己仍是只读角色。
    这样历史遗留/人工写入的非内置写权限角色不会因为 code 不在 RoleCode.ALL 就被分配。
    """
    custom_roles = [role for role in roles_by_code.values() if not is_system_role(role.code)]
    if not custom_roles:
        return

    rows = (await db.execute(
        select(RolePermission.role_id, Permission.code)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(RolePermission.role_id.in_([role.id for role in custom_roles]))
    )).all()
    codes_by_role_id: dict[int, set[str]] = {role.id: set() for role in custom_roles}
    for role_id, permission_code in rows:
        codes_by_role_id.setdefault(role_id, set()).add(permission_code)

    invalid = [
        role.code
        for role in custom_roles
        if not _is_custom_readonly_permission_set(role.code, codes_by_role_id.get(role.id, set()))
    ]
    if invalid:
        raise ValidationFailedError(f"非内置角色必须是自定义只读角色才可分配: {sorted(invalid)}")


async def _get_role_by_code(db: AsyncSession, code: str, *, for_update: bool = False) -> Role:
    stmt = select(Role).where(Role.code == code)
    if for_update:
        stmt = stmt.with_for_update()
    role = (await db.execute(stmt)).scalar_one_or_none()
    if role is None:
        raise NotFoundError(f"角色不存在: {code}")
    return role


async def create_custom_role(db: AsyncSession, *, code: str, name: str,
                             description: str | None,
                             permission_codes: list[str],
                             actor_user_id: int | None = None,
                             actor_user_email: str | None = None,
                             request: Request | None = None) -> dict:
    role_code = _normalize_role_code(code)
    perm_codes = _normalize_permission_codes(permission_codes)
    perms = await _load_permissions(db, perm_codes)
    role = Role(code=role_code, name=name.strip(), description=description)
    db.add(role)
    try:
        await db.flush()
        for pcode in sorted(set(perm_codes) | set(_AUTH_BASE)):
            db.add(RolePermission(role_id=role.id, permission_id=perms[pcode].id))
        new_permissions = sorted(set(perm_codes) | set(_AUTH_BASE))
        await write_audit(
            db,
            resource_type=AuditResourceType.ROLE,
            action=AuditAction.CREATE,
            user_id=actor_user_id,
            user_email=actor_user_email,
            resource_id=role.code,
            request=request,
            extra={
                "role_code": role.code,
                "role_name": role.name,
                "new_permissions": new_permissions,
            },
            commit=False,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("角色 code 已存在") from exc
    await db.refresh(role)
    return _build_role(role, list(perms.values()))


async def update_custom_role(db: AsyncSession, *, code: str, name: str,
                             description: str | None,
                             permission_codes: list[str],
                             actor_user_id: int | None = None,
                             actor_user_email: str | None = None,
                             request: Request | None = None) -> dict:
    role = await _get_role_by_code(db, code.strip().upper(), for_update=True)
    old_permissions = await _load_role_permission_codes(db, role.id)
    _ensure_custom_readonly_role(role, old_permissions)
    perm_codes = _normalize_permission_codes(permission_codes)
    perms = await _load_permissions(db, perm_codes)

    old_name = role.name
    old_description = role.description
    role.name = name.strip()
    role.description = description
    await db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for pcode in sorted(set(perm_codes) | set(_AUTH_BASE)):
        db.add(RolePermission(role_id=role.id, permission_id=perms[pcode].id))
    new_permissions = sorted(set(perm_codes) | set(_AUTH_BASE))
    await write_audit(
        db,
        resource_type=AuditResourceType.ROLE,
        action=AuditAction.UPDATE,
        user_id=actor_user_id,
        user_email=actor_user_email,
        resource_id=role.code,
        request=request,
        extra={
            "role_code": role.code,
            "old_name": old_name,
            "new_name": role.name,
            "old_description": old_description,
            "new_description": role.description,
            "old_permissions": old_permissions,
            "new_permissions": new_permissions,
        },
        commit=False,
    )
    await db.commit()
    await db.refresh(role)
    return _build_role(role, list(perms.values()))


async def delete_custom_role(db: AsyncSession, *, code: str,
                             actor_user_id: int | None = None,
                             actor_user_email: str | None = None,
                             request: Request | None = None) -> None:
    role = await _get_role_by_code(db, code.strip().upper(), for_update=True)
    old_permissions = await _load_role_permission_codes(db, role.id)
    _ensure_custom_readonly_role(role, old_permissions)
    assigned = (await db.execute(
        select(func.count()).select_from(UserRole).where(UserRole.role_id == role.id)
    )).scalar_one()
    if assigned:
        raise ValidationFailedError("角色已分配给用户,请先移除用户角色")
    await write_audit(
        db,
        resource_type=AuditResourceType.ROLE,
        action=AuditAction.DELETE,
        user_id=actor_user_id,
        user_email=actor_user_email,
        resource_id=role.code,
        request=request,
        extra={
            "role_code": role.code,
            "role_name": role.name,
            "old_permissions": old_permissions,
        },
        commit=False,
    )
    await db.delete(role)
    await db.commit()
