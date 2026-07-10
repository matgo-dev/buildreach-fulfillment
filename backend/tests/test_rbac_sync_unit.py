import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.rbac.permissions_config import ROLE_PERMISSIONS
from app.rbac.constants import Permissions


@pytest.mark.asyncio
async def test_sync_seeds_admin_and_catalog_operator_roles_and_base_perms():
    import os
    dsn = os.environ.get("TEST_DATABASE_URL",
        "postgresql+psycopg://liujingjing@localhost:5433/fulfillment_test")
    engine = create_async_engine(dsn)
    from app.db.base import Base
    from app.db import models  # noqa: F401
    from app.rbac.sync import sync_rbac
    from app.seed import run_all_seeds
    from app.db.models.role import Role
    from app.db.models.permission import Permission
    from sqlalchemy import select
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.drop_all)
            await c.run_sync(Base.metadata.create_all)
        async with Session() as db:
            await sync_rbac(db)
            roles = {r.code for r in (await db.execute(select(Role))).scalars()}
            perms = {p.code for p in (await db.execute(select(Permission))).scalars()}
        assert roles == {"ADMIN", "CATALOG_OPERATOR"}
        assert "auth:login" in perms
        assert "user:manage" in perms
        assert not any(p.startswith(("product:", "rfq:")) for p in perms)
        assert not any(p in perms for p in ("spu:manage", "sku:manage"))
        assert {"customer:manage", "catalog:read", "catalog:manage", "quote:manage"} <= perms
    finally:
        # 本测试对共享 fulfillment_test 做了 drop_all/create_all,会冲掉 session 级 fixture
        # 种下的引导管理员(sync_rbac 只建角色/权限,不建 admin 用户)。恢复基线:重跑
        # run_all_seeds 重种引导管理员,避免污染后续用 superadmin_headers 的测试(隔离修复)。
        async with Session() as db:
            await run_all_seeds(db)
        await engine.dispose()


def test_catalog_operator_has_read_and_manage():
    perms = ROLE_PERMISSIONS["CATALOG_OPERATOR"]
    assert Permissions.CATALOG_READ in perms
    assert Permissions.CATALOG_MANAGE in perms


def test_admin_has_catalog_read_but_not_manage():
    perms = ROLE_PERMISSIONS["ADMIN"]
    assert Permissions.CATALOG_READ in perms
    assert Permissions.CATALOG_MANAGE not in perms
