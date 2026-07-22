"""pytest fixtures（PostgreSQL · brew @16 端口 5433）。

隔离方案（SAVEPOINT 优化版，从 5min+ 降到 ~1min）:
- session-scope: 一个引擎 + 一次 schema 创建 + 一次 RBAC/seed
- function-scope: 每测试一条连接 + 外层事务 + SAVEPOINT，测后回滚到 seed 初始态
- 不依赖 alembic 迁移 — 直接 Base.metadata.create_all

事件循环: pyproject.toml 设置 asyncio_default_fixture_loop_scope = "session"，
所有 fixture 和测试共享同一个 session-scope 事件循环。
测试 DB 覆盖: 可通过环境变量 TEST_DATABASE_URL 覆盖默认 DSN。

M0 基座裁剪版：无 i18n/邮箱验证码/品类 seed 等业务耦合。
"""
from __future__ import annotations

import os

# 测试环境必要变量（置默认值避免 .env 缺失）
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-please-change-1234567890")
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://liujingjing@localhost:5433/fulfillment_test",
    ),
)
os.environ.setdefault("SUPER_ADMIN_EMAIL", "superadmin@fulfillment.local")
os.environ.setdefault("SUPER_ADMIN_INITIAL_PASSWORD", "Aa123456789")
# bcrypt 降到 4 rounds:单次 hash 从 ~500ms 降到 ~2ms,auth fixture 密集,整套提速 4-5×。
# 仅测试环境;生产走 config 默认 12。
os.environ.setdefault("BCRYPT_ROUNDS", "4")
# 测试按生产默认值跑(本地 backend/.env 会开 true;环境变量优先级高于 dotenv,固定住)
os.environ.setdefault("ENABLE_API_DOCS", "false")

from typing import AsyncGenerator  # noqa: E402

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base  # noqa: E402
from app.db import models as _models  # noqa: E402,F401  注册模型
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.rbac.sync import sync_rbac  # noqa: E402
from app.seed import run_all_seeds  # noqa: E402
from app.services.rate_limit import login_rate_limiter  # noqa: E402

# 测试引擎使用 psycopg 驱动（asyncpg 的 task 亲和性限制
# 导致 Starlette BaseHTTPMiddleware 新 task 中无法复用同一连接，
# psycopg3 async 无此限制，可安全跨 task 共享连接实现 SAVEPOINT 隔离）
_raw_dsn = os.environ["DATABASE_URL"]
TEST_DSN = _raw_dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)

# 护栏:本套件的 session fixture 会无条件 drop_all。若 DATABASE_URL 误指向非测试库
# (曾把 dev 库整清过),必须在任何 fixture / drop_all 之前 fail-fast。
# 判据:库名(DSN 最后一段,去掉 ?query)须以 `_test` 结尾(或恰为 `test`)。
# 用后缀而非子串——否则 `fulfillment_dev_test_x` 这类 dev 库会被误放行;
# 也不写死具体库名,好让 TEST_DATABASE_URL 指向自定义的 `*_test` 库。
_db_name = _raw_dsn.rsplit("/", 1)[-1].split("?", 1)[0].lower()
if _db_name != "test" and not _db_name.endswith("_test"):
    raise RuntimeError(
        f"拒绝在非测试库上跑测试:DATABASE_URL 指向 '{_db_name}'(库名须以 '_test' 结尾)。"
        f"本套件会 drop_all 清库 —— 显式 DATABASE_URL 指向 dev/prod 会清空数据。"
    )

# 引导管理员改密后的固定密码（测试用）
_BOOTSTRAP_NEW_PASSWORD = "TestNewPass999"


# ─── session-scope: 引擎 + schema + seed（仅一次）───────────────

@pytest_asyncio.fixture(scope="session")
async def _engine():
    """全 session 共用：建引擎、建表、跑 RBAC+seed，仅一次。"""
    engine = create_async_engine(TEST_DSN, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    _Session = async_sessionmaker(engine, expire_on_commit=False)
    async with _Session() as db:
        await sync_rbac(db)
        await run_all_seeds(db)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ─── function-scope: 每测试一条连接 + 事务回滚隔离 ────────────

@pytest_asyncio.fixture
async def _connection(_engine) -> AsyncGenerator[AsyncConnection, None]:
    """每个测试函数：一条连接 + 外层事务，测后回滚恢复到 seed 初始状态。"""
    async with _engine.connect() as conn:
        txn = await conn.begin()
        yield conn
        await txn.rollback()


def _add_savepoint_listener(async_session: AsyncSession) -> None:
    """让 session.commit() 释放 SAVEPOINT 后自动开启新 SAVEPOINT。

    这样 service 代码里的 db.commit() 只释放 SAVEPOINT 而非真正提交，
    且后续操作仍在 SAVEPOINT 保护下。
    """
    @event.listens_for(async_session.sync_session, "after_transaction_end")
    def restart_savepoint(session, transaction):  # type: ignore[no-untyped-def]
        if transaction.nested and not transaction._parent.nested:
            session.begin_nested()


@pytest_asyncio.fixture
async def db_session(_connection) -> AsyncGenerator[AsyncSession, None]:
    """绑定到测试连接的 session，SAVEPOINT 隔离。

    - flush() 或 commit() 都安全：commit 只释放 SAVEPOINT，listener 自动续建
    - 与 client 共享同一 _connection，数据互通
    """
    await _connection.begin_nested()
    session = AsyncSession(bind=_connection, expire_on_commit=False)
    _add_savepoint_listener(session)
    yield session
    await session.close()


@pytest_asyncio.fixture
async def client(_connection) -> AsyncGenerator[AsyncClient, None]:
    """HTTP 测试客户端，get_db 覆写为从测试连接拿 SAVEPOINT session。"""

    async def override_get_db():
        await _connection.begin_nested()
        session = AsyncSession(bind=_connection, expire_on_commit=False)
        _add_savepoint_listener(session)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    app.dependency_overrides[get_db] = override_get_db
    login_rate_limiter.clear_all()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    login_rate_limiter.clear_all()


@pytest_asyncio.fixture
async def superadmin_headers(client) -> dict[str, str]:
    """引导管理员：登录 → 改密（清 must_change_password）→ 重登，返回可用 headers。

    v0.1 加固后 must_change_password=True 的账号调非豁免端点会 403/40007，
    测试中需要先完成改密才能操作业务/系统 API。
    """
    from app.core.config import settings

    # 1. 初始登录
    r = await client.post(
        "/api/v1/auth/login",
        json={
            "identifier": settings.SUPER_ADMIN_EMAIL,
            "password": settings.SUPER_ADMIN_INITIAL_PASSWORD,
        },
    )
    assert r.status_code == 200
    token = r.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. 改密（豁免端点，must_change 期间可用）
    r2 = await client.post(
        "/api/v1/auth/change-password",
        headers=headers,
        json={
            "old_password": settings.SUPER_ADMIN_INITIAL_PASSWORD,
            "new_password": _BOOTSTRAP_NEW_PASSWORD,
        },
    )
    assert r2.status_code == 200

    # 3. 用新密码重新登录
    r3 = await client.post(
        "/api/v1/auth/login",
        json={"identifier": settings.SUPER_ADMIN_EMAIL, "password": _BOOTSTRAP_NEW_PASSWORD},
    )
    assert r3.status_code == 200
    new_token = r3.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {new_token}"}


@pytest_asyncio.fixture
async def product_operator_headers(client, db_session) -> dict[str, str]:
    """建一个 PRODUCT_OPERATOR 账号并返回可用 headers（must_change_password=False）。

    注：本仓库当前没有 /api/v1/users 创建用户的 HTTP 端点（`grep -rn 'api/v1/users'
    backend/app/api` 无匹配，`app/services/user_service.create_internal_user` 尚未接
    路由），所以直接走 service 层建号，再用 /api/v1/auth/login 拿 token。
    """
    from app.services.user_service import create_internal_user

    email = "product_op@fulfillment.local"
    pw = "CatalogOp12345"
    await create_internal_user(
        db_session,
        email=email,
        name="商品运营",
        password=pw,
        role="PRODUCT_OPERATOR",
        must_change_password=False,
        actor_user_id=0,
        actor_user_email="system@test",
    )
    r = await client.post(
        "/api/v1/auth/login", json={"identifier": email, "password": pw}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest_asyncio.fixture
async def sales_headers(client, db_session) -> dict[str, str]:
    """SALES 账号 headers。quote:manage 已从 ADMIN 摘除(Q25),报价操作须用销售角色。"""
    from app.services.user_service import create_internal_user

    email = "sales@fulfillment.local"
    pw = "SalesOp123456"
    await create_internal_user(
        db_session, email=email, name="销售", password=pw, role="SALES",
        must_change_password=False, actor_user_id=0, actor_user_email="system@test")
    r = await client.post("/api/v1/auth/login", json={"identifier": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest_asyncio.fixture
async def sales_readonly_headers(client, db_session) -> dict[str, str]:
    """合成角色:仅持 sales:read(+ auth base),**不持 inventory:read**。
    用于库存增量负例——SO 详情对无 inventory:read 者不下发 stock_balances 键。
    合成角色不在 RoleCode.ALL,故不走 create_internal_user,直接建 Role/RolePermission/User。"""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.db.models.permission import Permission
    from app.db.models.role import Role, RoleScope
    from app.db.models.role_permission import RolePermission
    from app.db.models.user import User, UserStatus
    from app.db.models.user_role import UserRole
    from app.rbac.constants import Permissions

    role = Role(code="SALES_RO_TEST", name="只读销售(测试)",
                scope=RoleScope.GLOBAL, description="仅 sales:read 合成角色")
    db_session.add(role)
    await db_session.flush()
    codes = [Permissions.AUTH_LOGIN, Permissions.AUTH_LOGOUT, Permissions.AUTH_ME,
             Permissions.SALES_READ]
    perm_ids = (await db_session.execute(
        select(Permission.id).where(Permission.code.in_(codes)))).scalars().all()
    for pid in perm_ids:
        db_session.add(RolePermission(role_id=role.id, permission_id=pid))
    email, pw = "sales_ro@fulfillment.local", "SalesRo123456"
    user = User(email=email, name="只读销售", password_hash=hash_password(pw),
                status=UserStatus.ACTIVE, must_change_password=False)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"identifier": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest_asyncio.fixture
async def product_readonly_headers(client, db_session) -> dict[str, str]:
    """合成角色:仅持 product:read(+ auth base),无 product:manage、无成本轴。
    ADMIN 摘除 product:read 过渡桥后,商品读/成本脱敏边界测试改用此纯只读身份,
    不再借 ADMIN 当只读脚手架。合成角色不在 RoleCode.ALL,直接建 Role/RolePermission/User。"""
    from sqlalchemy import select

    from app.core.security import hash_password
    from app.db.models.permission import Permission
    from app.db.models.role import Role, RoleScope
    from app.db.models.role_permission import RolePermission
    from app.db.models.user import User, UserStatus
    from app.db.models.user_role import UserRole
    from app.rbac.constants import Permissions

    role = Role(code="PRODUCT_RO_TEST", name="只读商品(测试)",
                scope=RoleScope.GLOBAL, description="仅 product:read 合成角色")
    db_session.add(role)
    await db_session.flush()
    codes = [Permissions.AUTH_LOGIN, Permissions.AUTH_LOGOUT, Permissions.AUTH_ME,
             Permissions.PRODUCT_READ]
    perm_ids = (await db_session.execute(
        select(Permission.id).where(Permission.code.in_(codes)))).scalars().all()
    for pid in perm_ids:
        db_session.add(RolePermission(role_id=role.id, permission_id=pid))
    email, pw = "product_ro@fulfillment.local", "ProductRo123456"
    user = User(email=email, name="只读商品", password_hash=hash_password(pw),
                status=UserStatus.ACTIVE, must_change_password=False)
    db_session.add(user)
    await db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", json={"identifier": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest_asyncio.fixture
async def purchaser_headers(client, db_session) -> dict[str, str]:
    """PURCHASER 账号 headers。持 supplier:*/purchase:*(含 read_cost)+ sales:read(发起采购)。"""
    from app.services.user_service import create_internal_user

    email = "purchaser@fulfillment.local"
    pw = "PurchaseOp123456"
    await create_internal_user(
        db_session, email=email, name="采购员", password=pw, role="PURCHASER",
        must_change_password=False, actor_user_id=0, actor_user_email="system@test")
    r = await client.post("/api/v1/auth/login", json={"identifier": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest_asyncio.fixture
async def logistics_headers(client, db_session) -> dict[str, str]:
    """LOGISTICS 账号 headers。持 outbound:*/shipment:* + sales:read/inventory:read/product:read。
    不持 receivable:read(应收=客户售价整表门控)、不持成本轴(出库/柜零金额)。"""
    from app.services.user_service import create_internal_user

    email = "logistics@fulfillment.local"
    pw = "LogisticsOp123456"
    await create_internal_user(
        db_session, email=email, name="物流仓运", password=pw, role="LOGISTICS",
        must_change_password=False, actor_user_id=0, actor_user_email="system@test")
    r = await client.post("/api/v1/auth/login", json={"identifier": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest_asyncio.fixture
async def finance_headers(client, db_session) -> dict[str, str]:
    """FINANCE 账号 headers。持 receipt:*/payment:*(含红线 payment)+ receivable:read/payable:read。
    统管收付款登记与核销/反核销。"""
    from app.services.user_service import create_internal_user

    email = "finance@fulfillment.local"
    pw = "FinanceOp123456"
    await create_internal_user(
        db_session, email=email, name="财务", password=pw, role="FINANCE",
        must_change_password=False, actor_user_id=0, actor_user_email="system@test")
    r = await client.post("/api/v1/auth/login", json={"identifier": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}
