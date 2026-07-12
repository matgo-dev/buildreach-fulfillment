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
from app.db.models.category_spec_attribute import SuggestionSource
from app.db.models.role import Role, RoleCode
from app.db.models.unit import Unit
from app.db.models.user import User, UserStatus
from app.db.models.user_role import UserRole
from app.services import spec_template_service as tmpl

logger = logging.getLogger(__name__)

# 常用售卖单位种子 —— 单位数据的**唯一源头**(单一源头约束)。迁移只建空 units 表,
# 不写死种子;生产与测试(create_all)两条路径都靠这里 seed。code 纯 ASCII、稳定、永久不变。
_UNIT_SEEDS: list[tuple[str, dict, int]] = [
    ("piece", {"zh": "件", "en": "pc"}, 10),
    ("meter", {"zh": "米", "en": "m"}, 20),
    ("sqm", {"zh": "平方米", "en": "sqm"}, 30),
    ("cbm", {"zh": "立方米", "en": "cbm"}, 40),
    ("kg", {"zh": "千克", "en": "kg"}, 50),
    ("ton", {"zh": "吨", "en": "ton"}, 60),
    ("roll", {"zh": "卷", "en": "roll"}, 70),
    ("bag", {"zh": "包", "en": "bag"}, 80),
    ("box", {"zh": "箱", "en": "box"}, 90),
    ("set", {"zh": "套", "en": "set"}, 100),
    ("pair", {"zh": "双", "en": "pair"}, 110),
]

_SPEC_TEMPLATE_SEEDS: dict[str, list[dict]] = {
    # category_code: 属性列表(种子;仅 zh,英/斯按需后补)。sort_order 由 upsert_attribute
    # 按列表顺序自动递增分配,此处无需手写。
    "10": [
        {"key": "material", "label_i18n": {"zh": "材质"}, "value_type": "enum", "options": [
            {"code": "carbon_steel", "label_i18n": {"zh": "碳钢"}},
            {"code": "stainless_steel", "label_i18n": {"zh": "不锈钢"}},
            {"code": "galvanized", "label_i18n": {"zh": "镀锌"}},
        ]},
        {"key": "dn", "label_i18n": {"zh": "公称通径"}, "value_type": "string"},
        {"key": "pressure", "label_i18n": {"zh": "压力等级"}, "value_type": "number", "unit": "MPa"},
        {"key": "conn", "label_i18n": {"zh": "连接方式"}, "value_type": "enum", "options": [
            {"code": "flange", "label_i18n": {"zh": "法兰"}},
            {"code": "thread", "label_i18n": {"zh": "螺纹"}},
            {"code": "weld", "label_i18n": {"zh": "焊接"}},
        ]},
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
    """批量 upsert 分类规格属性模板(source=seed)。

    幂等:分类不存在则跳过该分类;upsert_attribute 内部 ON CONFLICT(category_code,key)
    DO NOTHING,已存在的 key 原样保留不覆盖。
    注:种子挂在 category_code="10"——需与真实导入的分类 code 对齐;若导入数据
    无 "10",种子会跳过(幂等安全),运营导入真实分类后可调整种子 code 或改用
    upsert 服务补。
    """
    for category_code, attrs in _SPEC_TEMPLATE_SEEDS.items():
        cat = (await db.execute(
            select(Category).where(Category.code == category_code))).scalar_one_or_none()
        if cat is None:
            logger.info("Seed: category %s 不存在,跳过模板种子", category_code)
            continue
        for attr in attrs:
            await tmpl.upsert_attribute(
                db, category_code, key=attr["key"], label_i18n=attr["label_i18n"],
                value_type=attr.get("value_type", "string"), unit=attr.get("unit"),
                options=attr.get("options"), source=SuggestionSource.SEED)
    await db.commit()


async def seed_units(db: AsyncSession) -> None:
    """种入常用售卖单位(spec §11 Part A)。幂等:code 已存在则跳过,不覆盖。

    单位种子的唯一源头(迁移只建空表)。部署与测试(create_all)都经 run_all_seeds
    调用本函数填 units;skus 建行前 units 必须先有数据,否则 unit FK 违约。
    """
    for code, label_i18n, sort_order in _UNIT_SEEDS:
        existing = (await db.execute(select(Unit).where(Unit.code == code))).scalar_one_or_none()
        if existing is not None:
            continue
        db.add(Unit(code=code, label_i18n=label_i18n, sort_order=sort_order, is_active=True))
    await db.commit()


async def run_all_seeds(db: AsyncSession) -> None:
    """启动种子总入口。M0 基座仅保留引导管理员。"""
    await seed_bootstrap_admin(db)
    await seed_units(db)
    await seed_spec_templates(db)
