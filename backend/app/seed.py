"""基座种子:仅引导管理员(env 注入,must_change_password=True)。"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.config import settings
from app.core.security import hash_password
from app.db.models.role import Role, RoleCode
from app.db.models.user import User, UserStatus
from app.db.models.user_role import UserRole

logger = logging.getLogger(__name__)


async def seed_bootstrap_admin(db: AsyncSession) -> None:
    """种入引导管理员(env 注入密码,must_change_password=True)。

    幂等:已存在则跳过。环境变量键名不变(SUPER_ADMIN_*)。
    """
    email = settings.SUPER_ADMIN_EMAIL
    row = await db.execute(select(User).where(User.email == email))
    if row.scalar_one_or_none() is not None:
        logger.info("Seed: bootstrap admin %s already exists — kept as-is.", email)
        return

    role_row = await db.execute(select(Role).where(Role.code == RoleCode.ADMIN))
    admin_role = role_row.scalar_one_or_none()
    if admin_role is None:
        logger.error("Seed: ADMIN role missing, did rbac sync run first?")
        return

    user = User(
        email=email,
        name="Bootstrap Admin",
        password_hash=hash_password(settings.SUPER_ADMIN_INITIAL_PASSWORD),
        status=UserStatus.ACTIVE,
        must_change_password=True,
    )
    db.add(user)
    await db.flush()
    db.add(UserRole(user_id=user.id, role_id=admin_role.id))

    await write_audit(
        db,
        resource_type=AuditResourceType.USER,
        action=AuditAction.CREATE,
        user_id=user.id,
        user_email=user.email,
        resource_id=user.id,
        extra={"reason": "seed_bootstrap_admin", "role": RoleCode.ADMIN},
        commit=False,
    )
    await db.commit()
    logger.warning(
        "Seed: bootstrap admin %s created with initial password from env. "
        "**MUST change password on first login**.",
        email,
    )


async def run_all_seeds(db: AsyncSession) -> None:
    """启动种子总入口。M0 基座仅保留引导管理员。"""
    await seed_bootstrap_admin(db)
