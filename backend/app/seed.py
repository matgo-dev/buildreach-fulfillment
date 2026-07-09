"""基座种子:仅引导管理员(env 注入,must_change_password=True)。"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.config import settings
from app.core.security import hash_password
from app.db.models.category import Category
from app.db.models.category_spec_suggestion import CategorySpecSuggestion, SuggestionSource
from app.db.models.role import Role, RoleCode
from app.db.models.user import User, UserStatus
from app.db.models.user_role import UserRole

logger = logging.getLogger(__name__)

_SPEC_TEMPLATE_SEEDS: dict[str, list[dict]] = {
    # category_code: suggestions(种子;仅 zh,英/斯按需后补)
    "10": [
        {"key": "material", "label_i18n": {"zh": "材质"}, "value_type": "enum", "unit": "", "sort_order": 10, "source": SuggestionSource.SEED},
        {"key": "dn", "label_i18n": {"zh": "公称通径"}, "value_type": "string", "unit": "", "sort_order": 20, "source": SuggestionSource.SEED},
        {"key": "pressure", "label_i18n": {"zh": "压力等级"}, "value_type": "number", "unit": "MPa", "sort_order": 30, "source": SuggestionSource.SEED},
        {"key": "conn", "label_i18n": {"zh": "连接方式"}, "value_type": "enum", "unit": "", "sort_order": 40, "source": SuggestionSource.SEED},
    ],
}


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


async def seed_spec_templates(db: AsyncSession) -> None:
    """种入分类规格建议模板(source=种子)。

    幂等:分类不存在或该分类建议已存在则跳过。
    注:种子挂在 category_code="10"——需与真实导入的分类 code 对齐;若导入数据
    无 "10",种子会跳过(幂等安全),运营导入真实分类后可调整种子 code 或改用
    upsert 服务补。
    """
    for category_code, suggestions in _SPEC_TEMPLATE_SEEDS.items():
        cat = (await db.execute(
            select(Category).where(Category.code == category_code))).scalar_one_or_none()
        if cat is None:
            logger.info("Seed: category %s 不存在,跳过模板种子", category_code)
            continue
        exists = (await db.execute(select(CategorySpecSuggestion).where(
            CategorySpecSuggestion.category_code == category_code))).scalar_one_or_none()
        if exists is not None:
            continue
        db.add(CategorySpecSuggestion(category_code=category_code, suggestions=suggestions))
    await db.commit()


async def run_all_seeds(db: AsyncSession) -> None:
    """启动种子总入口。M0 基座仅保留引导管理员。"""
    await seed_bootstrap_admin(db)
    await seed_spec_templates(db)
