import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.mark.asyncio
async def test_sync_seeds_only_admin_role_and_base_perms():
    import os
    dsn = os.environ.get("TEST_DATABASE_URL",
        "postgresql+psycopg://liujingjing@localhost:5433/fulfillment_test")
    engine = create_async_engine(dsn)
    from app.db.base import Base
    from app.db import models  # noqa: F401
    from app.rbac.sync import sync_rbac
    from app.db.models.role import Role
    from app.db.models.permission import Permission
    from sqlalchemy import select
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        await sync_rbac(db)
        roles = {r.code for r in (await db.execute(select(Role))).scalars()}
        perms = {p.code for p in (await db.execute(select(Permission))).scalars()}
    await engine.dispose()
    assert roles == {"ADMIN"}
    assert "auth:login" in perms
    assert "user:manage" in perms
    assert not any(p.startswith(("product:", "rfq:", "quote:")) for p in perms)
