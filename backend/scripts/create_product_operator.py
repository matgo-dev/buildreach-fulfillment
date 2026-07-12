"""一次性开发脚本(非产品功能):为本地 QA 建一个 PRODUCT_OPERATOR 账号。

启动 seed 只种只读 ADMIN(`app/seed.py`);商品增改需 PRODUCT_OPERATOR 角色的账号。
生产环境的运营账号由 ADMIN 经用户/角色管理授予(不在此脚本、不进 seed —— 避免默认
密码账号落进生产,职责分离见 permissions_config.py)。此脚本仅供本地把前端商品目录
跑通做可视化走查。

CLI:
    python -m scripts.create_product_operator \\
        --email op@example.com --name 商品运营 --password Passw0rd!
幂等:账号已存在则仅补齐 PRODUCT_OPERATOR 角色绑定。
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.role import Role, RoleCode
from app.db.models.user import User, UserStatus
from app.db.models.user_role import UserRole
from app.db.session import AsyncSessionLocal


async def create_product_operator(
    db: AsyncSession, *, email: str, name: str, password: str
) -> str:
    role = (await db.execute(
        select(Role).where(Role.code == RoleCode.PRODUCT_OPERATOR))).scalar_one_or_none()
    if role is None:
        return ("PRODUCT_OPERATOR 角色不存在 —— 先启动一次后端(rbac 启动同步会建角色),再跑本脚本。")

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(
            email=email, name=name, password_hash=hash_password(password),
            status=UserStatus.ACTIVE, must_change_password=False,  # QA 直登,免改密
        )
        db.add(user)
        await db.flush()
        created = True
    else:
        created = False

    existing = (await db.execute(select(UserRole).where(
        UserRole.user_id == user.id, UserRole.role_id == role.id))).scalar_one_or_none()
    if existing is None:
        db.add(UserRole(user_id=user.id, role_id=role.id))

    await db.commit()
    verb = "已创建" if created else "已存在(补齐角色绑定)"
    return f"PRODUCT_OPERATOR 账号 {verb}:{email}"


async def _main() -> None:
    parser = argparse.ArgumentParser(description="建本地 QA 用 PRODUCT_OPERATOR 账号")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="商品运营")
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        msg = await create_product_operator(
            db, email=args.email, name=args.name, password=args.password)
    print(msg)


if __name__ == "__main__":
    asyncio.run(_main())
