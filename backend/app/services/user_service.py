"""内部账号管理 service。"""
from __future__ import annotations

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailedError
from app.core.security import PASSWORD_RULE_MESSAGE, hash_password, validate_password_strength
from app.db.models.permission import Permission
from app.db.models.role import Role, RoleCode
from app.db.models.role_permission import RolePermission
from app.db.models.user import User, UserStatus
from app.db.models.user_role import UserRole
from app.rbac.constants import Permissions


def _selectable_salespersons_stmt():
    """"可选报价人"口径单一源头:ACTIVE 且持 quote:manage。列表下拉与写入口校验共用同一
    谓词(不在两处各写一份、防漂移)。"""
    return (
        select(User.id, User.name)
        .join(UserRole, UserRole.user_id == User.id)
        .join(RolePermission, RolePermission.role_id == UserRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(Permission.code == Permissions.QUOTE_MANAGE, User.status == UserStatus.ACTIVE)
    )


async def list_selectable_salespersons(db: AsyncSession) -> list[dict]:
    """报价人选择器数据源:只回 {id,name}(不下发敏感字段/邮箱/手机,也不要求 user:manage)。"""
    stmt = _selectable_salespersons_stmt().distinct().order_by(User.name)
    return [{"id": r.id, "name": r.name} for r in (await db.execute(stmt)).all()]


async def is_selectable_salesperson(db: AsyncSession, user_id: int) -> bool:
    """报价写入口守卫:该用户是否满足"可选报价人"口径(同 list 单一源头)。前端下拉挡不住
    直连 API,服务端据此硬挡把报价归给非销售/停用/任意存在用户。"""
    stmt = _selectable_salespersons_stmt().where(User.id == user_id)
    return (await db.execute(stmt)).first() is not None

ALLOWED_INTERNAL_ROLES = {RoleCode.ADMIN, RoleCode.PRODUCT_OPERATOR, RoleCode.SALES,
                          RoleCode.PURCHASER}


async def create_internal_user(
    db: AsyncSession,
    *,
    email: str,
    name: str,
    password: str,
    role: str,
    must_change_password: bool,
    actor_user_id: int,
    actor_user_email: str,
    username: str | None = None,
    request: Request | None = None,
) -> User:
    if role not in ALLOWED_INTERNAL_ROLES:
        # 业务用户必须走自助注册
        raise ValidationFailedError(
            f"该接口仅允许创建 {sorted(ALLOWED_INTERNAL_ROLES)},BUYER/SUPPLIER 请走自助注册"
        )
    if not validate_password_strength(password):
        raise ValidationFailedError(PASSWORD_RULE_MESSAGE)
    # 排除已停用账号,允许复用
    row = await db.execute(
        select(User.id).where(User.email == email, User.status != UserStatus.DISABLED)
    )
    if row.scalar_one_or_none() is not None:
        raise ConflictError("Email 已存在")
    if username:
        row2 = await db.execute(
            select(User.id).where(User.username == username, User.status != UserStatus.DISABLED)
        )
        if row2.scalar_one_or_none() is not None:
            raise ConflictError("用户名已存在")

    role_row = await db.execute(select(Role).where(Role.code == role))
    role_obj = role_row.scalar_one_or_none()
    if role_obj is None:
        raise NotFoundError(f"Role not found: {role}")

    user = User(
        email=email,
        username=username,
        name=name,
        password_hash=hash_password(password),
        status=UserStatus.ACTIVE,
        must_change_password=must_change_password,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=role_obj.id))

    await write_audit(
        db,
        resource_type=AuditResourceType.USER,
        action=AuditAction.CREATE,
        user_id=actor_user_id,
        user_email=actor_user_email,
        resource_id=user.id,
        request=request,
        extra={"created_user_email": user.email, "role": role},
        commit=False,
    )
    await write_audit(
        db,
        resource_type=AuditResourceType.USER_ROLE,
        action=AuditAction.ROLE_ASSIGN,
        user_id=actor_user_id,
        user_email=actor_user_email,
        resource_id=user.id,
        request=request,
        extra={"target_user_id": user.id, "role": role},
        commit=False,
    )
    await db.commit()
    await db.refresh(user)
    return user


async def list_users(
    db: AsyncSession,
    *,
    q: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[tuple[User, list[str]]], int]:
    """用户列表:筛选(状态/关键词 name|email|username)+ 分页,id 降序。"""
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    offset = (page - 1) * page_size

    conds = []
    if status:
        conds.append(User.status == status)
    if q:
        like = f"%{q}%"
        conds.append(or_(User.name.ilike(like), User.email.ilike(like),
                         User.username.ilike(like)))

    total = (await db.execute(select(func.count(User.id)).where(*conds))).scalar_one()
    rows = await db.execute(
        select(User).where(*conds).order_by(User.id.desc()).offset(offset).limit(page_size)
    )
    users = list(rows.scalars().all())
    if not users:
        return [], total

    role_rows = await db.execute(
        select(UserRole.user_id, Role.code)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id.in_([u.id for u in users]))
    )
    roles_by_user: dict[int, list[str]] = {}
    for uid, rcode in role_rows.all():
        roles_by_user.setdefault(uid, []).append(rcode)

    items = [(u, sorted(roles_by_user.get(u.id, []))) for u in users]
    return items, total


async def get_user_roles(db: AsyncSession, user_id: int) -> list[str]:
    """单用户角色 codes(写端点响应组装用)。"""
    rows = await db.execute(
        select(Role.code).join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id))
    return sorted(r for (r,) in rows.all())


async def update_user(
    db: AsyncSession,
    *,
    target_user_id: int,
    actor_user_id: int,
    actor_user_email: str,
    email: str | None = None,
    phone: str | None = None,
    name: str | None = None,
    request: Request | None = None,
) -> User:
    """Admin 编辑用户基本信息(email/phone/name)。"""
    target = await db.get(User, target_user_id)
    if target is None:
        raise NotFoundError("User not found")

    changes: dict = {}

    if name is not None and name != target.name:
        changes["name"] = {"old": target.name, "new": name}
        target.name = name

    if email is not None and email != target.email:
        # 检查邮箱唯一(排除 DISABLED)
        row = await db.execute(
            select(User.id).where(
                User.email == email,
                User.status != UserStatus.DISABLED,
                User.id != target.id,
            )
        )
        if row.scalar_one_or_none() is not None:
            raise ConflictError("该邮箱已被其他用户使用")
        changes["email"] = {"old": target.email, "new": email}
        target.email = email

    if phone is not None and phone != target.phone:
        # 检查手机号唯一(排除 DISABLED)
        row = await db.execute(
            select(User.id).where(
                User.phone == phone,
                User.status != UserStatus.DISABLED,
                User.id != target.id,
            )
        )
        if row.scalar_one_or_none() is not None:
            raise ConflictError("该手机号已被其他用户使用")
        changes["phone"] = {"old": target.phone, "new": phone}
        target.phone = phone

    if not changes:
        return target

    await write_audit(
        db,
        resource_type=AuditResourceType.USER,
        action=AuditAction.UPDATE,
        user_id=actor_user_id,
        user_email=actor_user_email,
        resource_id=target.id,
        request=request,
        extra={"changes": changes},
        commit=False,
    )
    await db.commit()
    await db.refresh(target)
    return target


async def _count_active_admins(db: AsyncSession) -> int:
    row = await db.execute(
        select(func.count(User.id.distinct()))
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(Role.code == RoleCode.ADMIN, User.status == UserStatus.ACTIVE)
    )
    return int(row.scalar_one())


async def _user_has_role(db: AsyncSession, user_id: int, role_code: str) -> bool:
    row = await db.execute(
        select(UserRole.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id, Role.code == role_code)
    )
    return row.scalar_one_or_none() is not None


async def disable_user(
    db: AsyncSession,
    *,
    target_user_id: int,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> User:
    """停用账号(status=DISABLED)。

    规则:
    - 不能停用自己
    - 不能停用 super admin(env 注入的零号账号)
    - 不能停用最后一个可用 ADMIN(防系统失联)
    - 已 DISABLED → 幂等返回,不写审计
    """
    target = await db.get(User, target_user_id)
    if target is None:
        raise NotFoundError("User not found")

    if target.id == actor_user_id:
        raise ValidationFailedError("不能停用自己的账号")

    if target.email == settings.SUPER_ADMIN_EMAIL:
        raise ValidationFailedError("不能停用 super admin 账号")

    if target.status == UserStatus.DISABLED:
        return target  # 幂等

    # 最后一个可用 ADMIN 保护
    if await _user_has_role(db, target.id, RoleCode.ADMIN):
        active_admins = await _count_active_admins(db)
        if active_admins <= 1:
            raise ValidationFailedError("系统至少保留一个可用 ADMIN,无法停用该账号")

    target.status = UserStatus.DISABLED

    await write_audit(
        db,
        resource_type=AuditResourceType.USER,
        action=AuditAction.USER_DISABLE,
        user_id=actor_user_id,
        user_email=actor_user_email,
        resource_id=target.id,
        request=request,
        extra={"target_user_id": target.id, "target_email": target.email},
        commit=False,
    )
    await db.commit()
    await db.refresh(target)
    return target


async def enable_user(
    db: AsyncSession,
    *,
    target_user_id: int,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> User:
    """启用账号(status=ACTIVE)。已 ACTIVE → 幂等返回。"""
    target = await db.get(User, target_user_id)
    if target is None:
        raise NotFoundError("User not found")

    if target.status == UserStatus.ACTIVE:
        return target

    target.status = UserStatus.ACTIVE

    await write_audit(
        db,
        resource_type=AuditResourceType.USER,
        action=AuditAction.USER_ENABLE,
        user_id=actor_user_id,
        user_email=actor_user_email,
        resource_id=target.id,
        request=request,
        extra={"target_user_id": target.id, "target_email": target.email},
        commit=False,
    )
    await db.commit()
    await db.refresh(target)
    return target


async def reset_password(
    db: AsyncSession,
    *,
    target_user_id: int,
    new_password: str,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> User:
    """管理员代重置密码:临时密码 + 强制首登改密 + token_version+1 踢掉全部旧会话。

    规则:
    - 不能重置自己(自助走 /auth/change-password,须验旧密码)
    - 不能重置 super admin(env 零号账号)
    """
    if not validate_password_strength(new_password):
        raise ValidationFailedError(PASSWORD_RULE_MESSAGE)
    target = await db.get(User, target_user_id)
    if target is None:
        raise NotFoundError("User not found")
    if target.id == actor_user_id:
        raise ValidationFailedError("不能重置自己的密码,请走修改密码")
    if target.email == settings.SUPER_ADMIN_EMAIL:
        raise ValidationFailedError("不能重置 super admin 密码")

    target.password_hash = hash_password(new_password)
    target.must_change_password = True
    target.token_version += 1

    await write_audit(
        db,
        resource_type=AuditResourceType.USER,
        action=AuditAction.PASSWORD_RESET,
        user_id=actor_user_id,
        user_email=actor_user_email,
        resource_id=target.id,
        request=request,
        extra={"target_user_id": target.id, "target_email": target.email},
        commit=False,
    )
    await db.commit()
    await db.refresh(target)
    return target
