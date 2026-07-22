"""refresh token 家族账本:轮换作废 + 重放检测(宽限窗)+ 单会话服务端吊销。

与 test_security_hardening.py 的「refresh 会话环」互补:那边测轮换/tv 吊销/非活跃拦截,
本文件测家族记账带来的新语义 —— 旧 token 轮换后作废、窗外重放撤整族、logout 服务端撤族。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_refresh_token
from app.db.models.refresh_token import RefreshToken
from app.services.rate_limit import login_rate_limiter
from app.services.user_service import create_internal_user

PW = "LockMe123456"
COOKIE = settings.REFRESH_COOKIE_NAME


async def _mk_user(db_session, email: str, *, role: str = "SALES"):
    return await create_internal_user(
        db_session, email=email, name="refresh家族测试", password=PW, role=role,
        must_change_password=False, actor_user_id=0, actor_user_email="system@test")


async def _login(client, email: str, password: str = PW):
    login_rate_limiter.clear_all()
    return await client.post(
        "/api/v1/auth/login", json={"identifier": email, "password": password})


def _cookie_val(resp) -> str:
    """从响应取下发的 refresh cookie 明文值。"""
    return resp.cookies[COOKIE]


async def _refresh_with(client, cookie_val: str):
    """用显式指定的 refresh cookie 打 /refresh(模拟重放旧 token,绕开 jar 里的新值)。

    直接下 Cookie 头 —— httpx 对无点主机名(base_url=http://test)的 cookie jar domain
    匹配会静默丢弃,显式头才保证真的发到服务端。
    """
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh", headers={"Cookie": f"{COOKIE}={cookie_val}"})
    client.cookies.clear()
    return resp


async def _rows_for(db_session, user_id: int) -> list[RefreshToken]:
    res = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id))
    return list(res.scalars().all())


async def _revoked_values(db_session, user_id: int) -> list:
    """列级取 revoked_at 值(不经 ORM identity map,反映另一 session 已提交的最新状态)。"""
    res = await db_session.execute(
        select(RefreshToken.revoked_at).where(RefreshToken.user_id == user_id))
    return [r[0] for r in res.all()]


# ─── 登录建族 ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_records_active_family_row(client, db_session):
    user = await _mk_user(db_session, "famlogin@fulfillment.local")
    r = await _login(client, user.email)
    assert r.status_code == 200

    rows = await _rows_for(db_session, user.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.family_id and len(row.family_id) == 32
    assert row.jti_hash and len(row.jti_hash) == 64
    assert row.used_at is None and row.revoked_at is None


# ─── 轮换:父标 used、同族派生子 ────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_consumes_parent_and_mints_child_in_family(client, db_session):
    user = await _mk_user(db_session, "famrotate@fulfillment.local")
    await _login(client, user.email)

    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200

    rows = await _rows_for(db_session, user.id)
    assert len(rows) == 2
    used = [x for x in rows if x.used_at is not None]
    fresh = [x for x in rows if x.used_at is None]
    assert len(used) == 1 and len(fresh) == 1
    # 同族
    assert used[0].family_id == fresh[0].family_id
    # 父指向后继
    assert used[0].replaced_by_jti_hash == fresh[0].jti_hash
    assert fresh[0].revoked_at is None


# ─── 窗外重放 → 撤整族 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_outside_grace_revokes_whole_family(client, db_session):
    user = await _mk_user(db_session, "famreplay@fulfillment.local")
    r1 = await _login(client, user.email)
    old_cookie = _cookie_val(r1)

    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200
    new_cookie = _cookie_val(r2)

    # 把父行 issued/used 整体挪到很久以前,used_at 落在宽限窗之外(模拟隔了很久旧 token 又出现);
    # issued 一并往前,满足 used_at >= issued_at 的 CHECK。
    rows = await _rows_for(db_session, user.id)
    parent = next(x for x in rows if x.used_at is not None)
    now = datetime.now(timezone.utc)
    parent.issued_at = now - timedelta(minutes=30)
    parent.used_at = now - timedelta(seconds=settings.REFRESH_REPLAY_GRACE_SECONDS + 60)
    await db_session.commit()

    # 重放旧 token → 401
    rr = await _refresh_with(client, old_cookie)
    assert rr.status_code == 401

    # 整族被撤:连合法的后继 token 也失效
    rn = await _refresh_with(client, new_cookie)
    assert rn.status_code == 401
    revoked = await _revoked_values(db_session, user.id)
    assert len(revoked) == 2 and all(v is not None for v in revoked)


# ─── 窗内重放 → 容忍,不撤族 ────────────────────────────────────

@pytest.mark.asyncio
async def test_replay_within_grace_tolerated_no_revoke(client, db_session):
    user = await _mk_user(db_session, "famgrace@fulfillment.local")
    r1 = await _login(client, user.email)
    old_cookie = _cookie_val(r1)

    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200
    new_cookie = _cookie_val(r2)

    # 立即用旧 token 再刷(父 used_at 就在刚才,窗内)→ 容忍,发新
    rr = await _refresh_with(client, old_cookie)
    assert rr.status_code == 200

    # 族未被撤:先前的合法后继仍可用
    rn = await _refresh_with(client, new_cookie)
    assert rn.status_code == 200
    revoked = await _revoked_values(db_session, user.id)
    assert revoked and all(v is None for v in revoked)


@pytest.mark.asyncio
async def test_within_grace_reuse_does_not_extend_window(client, db_session):
    """窗内重放不刷新 used_at —— 否则持续每 59s 重放可无限撑开窗口(攻击面)。"""
    user = await _mk_user(db_session, "famnoext@fulfillment.local")
    r1 = await _login(client, user.email)
    old_cookie = _cookie_val(r1)

    await client.post("/api/v1/auth/refresh")
    rows = await _rows_for(db_session, user.id)
    parent = next(x for x in rows if x.used_at is not None)
    first_used_at = parent.used_at

    rr = await _refresh_with(client, old_cookie)
    assert rr.status_code == 200
    await db_session.refresh(parent)
    assert parent.used_at == first_used_at


# ─── logout 服务端撤族 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_logout_revokes_family_server_side(client, db_session):
    user = await _mk_user(db_session, "famlogout@fulfillment.local")
    r1 = await _login(client, user.email)
    stolen_cookie = _cookie_val(r1)

    r2 = await client.post("/api/v1/auth/logout")
    assert r2.status_code == 200

    # 被复制走的 cookie 也不能续命:族已在服务端撤销(非仅清浏览器 cookie)
    rr = await _refresh_with(client, stolen_cookie)
    assert rr.status_code == 401
    revoked = await _revoked_values(db_session, user.id)
    assert revoked and all(v is not None for v in revoked)


# ─── 未知 jti / 过期行 ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_unknown_jti_401(client, db_session):
    user = await _mk_user(db_session, "famunknown@fulfillment.local")
    # 造一个签名合法但从未记账的 refresh token(模拟伪造 / 已被清理的行)
    token, _jti = create_refresh_token(user.id, user.email, user.token_version)
    rr = await _refresh_with(client, token)
    assert rr.status_code == 401


@pytest.mark.asyncio
async def test_refresh_expired_row_401(client, db_session):
    user = await _mk_user(db_session, "famexpired@fulfillment.local")
    r1 = await _login(client, user.email)
    cookie = _cookie_val(r1)

    rows = await _rows_for(db_session, user.id)
    row = rows[0]
    # 同时挪 issued/expires 到过去,满足 CHECK(expires_at > issued_at)且已过期
    now = datetime.now(timezone.utc)
    row.issued_at = now - timedelta(days=8)
    row.expires_at = now - timedelta(days=1)
    await db_session.commit()

    rr = await _refresh_with(client, cookie)
    assert rr.status_code == 401


# ─── 改密签发的新族可用 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_change_password_issues_usable_family(client, db_session):
    user = await _mk_user(db_session, "fampwd@fulfillment.local")
    r1 = await _login(client, user.email)
    access = r1.json()["data"]["access_token"]

    new_pw = "NewPass123456"
    rc = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {access}"},
        json={"old_password": PW, "new_password": new_pw},
    )
    assert rc.status_code == 200
    new_cookie = _cookie_val(rc)

    # 改密后下发的 refresh token 有对应家族行,可正常轮换(非「有 token 无行 → 401」)
    rr = await _refresh_with(client, new_cookie)
    assert rr.status_code == 200


# ─── 登录惰性清理过期行 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_purges_expired_rows_including_chain(client, db_session):
    """过期的父子链(父 used+replaced_by 指向子)在下次登录时一条 DELETE 同批删净。

    同批删也验证自引用 FK / 配对 CHECK 不被 SET NULL 半路触发。
    """
    user = await _mk_user(db_session, "famclean@fulfillment.local")
    await _login(client, user.email)
    r2 = await client.post("/api/v1/auth/refresh")
    assert r2.status_code == 200

    # 把父子两行整体挪到过去:已过期(expires_at < now)且满足全部时序 CHECK
    now = datetime.now(timezone.utc)
    for row in await _rows_for(db_session, user.id):
        row.issued_at = now - timedelta(days=9)
        if row.used_at is not None:
            row.used_at = now - timedelta(days=9)
        row.expires_at = now - timedelta(days=2)
    await db_session.commit()

    r3 = await _login(client, user.email)
    assert r3.status_code == 200

    rows = await _rows_for(db_session, user.id)
    # 只剩本次登录新签的一行,旧父子链已被清理
    assert len(rows) == 1
    assert rows[0].expires_at > now and rows[0].used_at is None


@pytest.mark.asyncio
async def test_login_cleanup_is_global_and_spares_live_rows(client, db_session):
    """清理是全表谓词(任一登录清所有人的过期行),且不动未过期的活行。"""
    user_a = await _mk_user(db_session, "famcleana@fulfillment.local")
    user_b = await _mk_user(db_session, "famcleanb@fulfillment.local")

    # user_a 两个会话:一个过期、一个存活
    await _login(client, user_a.email)
    await _login(client, user_a.email)
    now = datetime.now(timezone.utc)
    a_rows = await _rows_for(db_session, user_a.id)
    a_rows[0].issued_at = now - timedelta(days=9)
    a_rows[0].expires_at = now - timedelta(days=2)
    await db_session.commit()

    # user_b 登录 → 触发全局清理
    rb = await _login(client, user_b.email)
    assert rb.status_code == 200

    a_left = await _rows_for(db_session, user_a.id)
    b_left = await _rows_for(db_session, user_b.id)
    assert len(a_left) == 1 and a_left[0].expires_at > now  # 过期行没了,活行还在
    assert len(b_left) == 1
