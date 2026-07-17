"""安全加固增量测试。

覆盖:账号级登录锁定全流程 / 防枚举归一(DEACTIVATED 泛化)/ refresh 会话环
(快乐路径 + 轮换 + tv 吊销 + 非 ACTIVE 拦截)/ logout 清 cookie 幂等 /
API 文档开关(默认关)/ 安全响应头 / attachments 端点下线。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.db.models.user import UserStatus
from app.services.rate_limit import login_rate_limiter
from app.services.user_service import create_internal_user

PW = "LockMe123456"


async def _mk_user(db_session, email: str, *, role: str = "SALES"):
    return await create_internal_user(
        db_session, email=email, name="安全加固测试", password=PW, role=role,
        must_change_password=False, actor_user_id=0, actor_user_email="system@test")


async def _login(client, email: str, password: str):
    # 每次清进程内限流(第一道减速带),专测第二道(落库账号锁)
    login_rate_limiter.clear_all()
    return await client.post(
        "/api/v1/auth/login", json={"identifier": email, "password": password})


# ─── 账号级登录锁定 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_account_lockout_full_cycle(client, db_session):
    email = "lockme@fulfillment.local"
    user = await _mk_user(db_session, email)

    # 连错 THRESHOLD 次:前 N-1 次泛化 401,第 N 次触发锁定(40010)
    for i in range(settings.ACCOUNT_LOCK_THRESHOLD):
        r = await _login(client, email, "WrongPass123")
        if i < settings.ACCOUNT_LOCK_THRESHOLD - 1:
            assert r.status_code == 401, r.text
            assert r.json()["code"] == 40001
        else:
            assert r.status_code == 429, r.text
            assert r.json()["code"] == 40010

    # 锁定落在用户行:locked_until 置位、计数清零
    await db_session.refresh(user)
    assert user.locked_until is not None
    assert user.failed_login_attempts == 0

    # 锁定期间正确密码也拒,且不递增计数
    r = await _login(client, email, PW)
    assert r.status_code == 429
    assert r.json()["code"] == 40010
    await db_session.refresh(user)
    assert user.failed_login_attempts == 0

    # locked_until 置过去 → 可再试,正确密码登录成功并清零解锁
    user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    r = await _login(client, email, PW)
    assert r.status_code == 200, r.text
    await db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


@pytest.mark.asyncio
async def test_failed_attempts_accumulate_on_user_row(client, db_session):
    email = "count@fulfillment.local"
    user = await _mk_user(db_session, email)
    for _ in range(3):
        r = await _login(client, email, "WrongPass123")
        assert r.status_code == 401
    await db_session.refresh(user)
    assert user.failed_login_attempts == 3

    # 登录成功清零
    r = await _login(client, email, PW)
    assert r.status_code == 200
    await db_session.refresh(user)
    assert user.failed_login_attempts == 0


@pytest.mark.asyncio
async def test_admin_reset_password_unlocks_account(client, db_session, superadmin_headers):
    email = "resetunlock@fulfillment.local"
    user = await _mk_user(db_session, email)
    user.failed_login_attempts = 7
    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    await db_session.commit()

    r = await client.post(
        f"/api/v1/users/{user.id}/reset-password",
        headers=superadmin_headers,
        json={"password": "NewTemp12345"},
    )
    assert r.status_code == 200, r.text
    await db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


# ─── 防枚举归一 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deactivated_login_indistinguishable_from_wrong_password(client, db_session):
    email = "deact@fulfillment.local"
    user = await _mk_user(db_session, email)

    r_wrong = await _login(client, email, "WrongPass123")
    assert r_wrong.status_code == 401

    user.status = UserStatus.DEACTIVATED
    await db_session.commit()
    r_deact = await _login(client, email, PW)

    # 同一 HTTP 状态 / 业务码 / 文案,响应层不可区分;真实原因只进审计
    assert r_deact.status_code == r_wrong.status_code == 401
    assert r_deact.json()["code"] == r_wrong.json()["code"] == 40001
    assert r_deact.json()["message"] == r_wrong.json()["message"]


# ─── refresh 会话环 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_happy_path_rotates_cookie(client, db_session):
    email = "refresh@fulfillment.local"
    await _mk_user(db_session, email)
    r = await _login(client, email, PW)
    assert r.status_code == 200
    assert settings.REFRESH_COOKIE_NAME in r.cookies

    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    assert data["access_token"] and data["token_type"] == "Bearer"
    # 轮换:响应重新下发 refresh cookie(滑动 7 天)
    set_cookie = r2.headers.get("set-cookie", "")
    assert settings.REFRESH_COOKIE_NAME in set_cookie

    # 新 access token 可用
    r3 = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_refresh_without_cookie_401(client):
    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_refresh_fails_after_token_version_bump(client, db_session):
    email = "tvbump@fulfillment.local"
    user = await _mk_user(db_session, email)
    r = await _login(client, email, PW)
    assert r.status_code == 200

    # 吊销:token_version 单一源头 +1(改密/管理员重置同机制)
    user.token_version += 1
    await db_session.commit()

    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 401
    # 失败即清 cookie(不留失效 token 反复打端点)
    assert settings.REFRESH_COOKIE_NAME in r2.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_refresh_fails_for_non_active_user(client, db_session):
    email = "refdeact@fulfillment.local"
    user = await _mk_user(db_session, email)
    r = await _login(client, email, PW)
    assert r.status_code == 200

    user.status = UserStatus.DEACTIVATED
    await db_session.commit()

    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 401


# ─── logout ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout_clears_cookie_and_is_idempotent(client, db_session):
    email = "logout@fulfillment.local"
    await _mk_user(db_session, email)
    r = await _login(client, email, PW)
    assert r.status_code == 200

    # 不带 Authorization 也幂等成功并清 cookie
    r2 = await client.post("/api/v1/auth/logout")
    assert r2.status_code == 200
    assert settings.REFRESH_COOKIE_NAME in r2.headers.get("set-cookie", "")

    # cookie 已清:refresh 失效
    r3 = await client.post("/api/v1/auth/refresh")
    assert r3.status_code == 401

    # 重复登出仍成功(幂等)
    r4 = await client.post("/api/v1/auth/logout")
    assert r4.status_code == 200


# ─── API 文档开关 / 响应头 / attachments 下线 ──────────────────

@pytest.mark.asyncio
async def test_api_docs_disabled_by_default(client):
    # conftest 固定 ENABLE_API_DOCS=false(生产默认值)
    assert (await client.get("/docs")).status_code == 404
    assert (await client.get("/redoc")).status_code == 404
    assert (await client.get("/openapi.json")).status_code == 404


@pytest.mark.asyncio
async def test_security_headers_present(client):
    r = await client.get("/healthz")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    # ENABLE_HSTS 默认 false:HTTP 阶段不下发 HSTS
    assert "strict-transport-security" not in r.headers


@pytest.mark.asyncio
async def test_attachments_endpoint_removed(client):
    files = {"file": ("x.txt", b"hi", "text/plain")}
    r = await client.post("/api/v1/attachments", files=files)
    assert r.status_code == 404
