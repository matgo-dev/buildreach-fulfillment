"""走查加固:登录时序等化 / bcrypt 异步 / 限流桶有界 / XFF 最右 / trace fullmatch /
FINANCE 取数权限 / 附件强制改密门。"""
from __future__ import annotations

import time

import pytest


class _StubReq:
    def __init__(self, headers: dict, client=None):
        self.headers = headers
        self.client = client


# ---------- bcrypt 异步 + 时序等化 ----------

@pytest.mark.asyncio
async def test_verify_password_async_contract():
    from app.core.security import hash_password, verify_password_async
    h = hash_password("secret123")
    assert await verify_password_async("secret123", h) is True
    assert await verify_password_async("wrong", h) is False
    # 账号不存在(hashed=None):恒 False,但仍会对 dummy hash 跑一次(等化耗时,契约上只暴露 False)
    assert await verify_password_async("anything", None) is False


@pytest.mark.asyncio
async def test_login_runs_bcrypt_even_for_unknown_user(client, monkeypatch):
    """登录时序枚举防护:用户不存在也跑一次密码校验(不短路),否则毫秒返回 vs ~0.3s 可枚举。"""
    import app.services.auth_service as svc
    real = svc.verify_password_async
    calls = {"n": 0}

    async def counting(plain, hashed):
        calls["n"] += 1
        return await real(plain, hashed)

    monkeypatch.setattr(svc, "verify_password_async", counting)
    r = await client.post("/api/v1/auth/login",
                          json={"identifier": "nobody@nowhere.local", "password": "whatever123"})
    assert r.status_code == 401
    assert calls["n"] == 1, "用户不存在时也应跑一次 bcrypt 校验(时序等化)"


# ---------- 限流桶有界 ----------

def test_rate_limiter_sweeps_fully_expired_bucket():
    from app.services.rate_limit import LoginRateLimiter
    limiter = LoginRateLimiter()
    limiter.record_failure("stale", "ip")
    b = limiter._buckets[limiter._key("stale", "ip")]
    b.failures = [0.0]           # 失败时间远在窗口之前
    b.locked_until = 0.0         # 无锁
    limiter._evict(time.time())
    assert limiter._key("stale", "ip") not in limiter._buckets, "已彻底过期的桶应被清"


def test_rate_limiter_bounded_under_key_flood():
    from app.services.rate_limit import LoginRateLimiter, _MAX_BUCKETS
    limiter = LoginRateLimiter()
    for i in range(_MAX_BUCKETS + 100):   # 随机 identifier 洪泛
        limiter.record_failure(f"user{i}", "1.1.1.1")
    assert len(limiter._buckets) <= _MAX_BUCKETS, "桶数不得越过硬上限"


# ---------- XFF 最右 / X-Real-IP 优先 ----------

def test_get_client_ip_takes_rightmost_xff(monkeypatch):
    from app.core import request_ip
    monkeypatch.setattr(request_ip.settings, "TRUST_PROXY", True)
    req = _StubReq(headers={"x-forwarded-for": "9.9.9.9, 2.2.2.2, 3.3.3.3"})
    assert request_ip.get_client_ip(req) == "3.3.3.3", "取反代追加的最右跳,非客户端可伪造的最左"


def test_get_client_ip_prefers_real_ip(monkeypatch):
    from app.core import request_ip
    monkeypatch.setattr(request_ip.settings, "TRUST_PROXY", True)
    req = _StubReq(headers={"x-real-ip": "8.8.8.8", "x-forwarded-for": "9.9.9.9, 3.3.3.3"})
    assert request_ip.get_client_ip(req) == "8.8.8.8"


# ---------- trace id fullmatch ----------

def test_trace_id_rejects_trailing_newline(monkeypatch):
    from app.audit import middleware
    monkeypatch.setattr(middleware.settings, "TRUST_INBOUND_TRACE_ID", True)
    assert middleware._safe_inbound_trace_id(
        _StubReq(headers={"X-Trace-Id": "validtrace123\n"})) is None
    assert middleware._safe_inbound_trace_id(
        _StubReq(headers={"X-Trace-Id": "validtrace123"})) == "validtrace123"


# ---------- FINANCE 取数权限(修流程断裂)----------

@pytest.mark.asyncio
async def test_finance_can_list_suppliers_and_customers(client, finance_headers):
    """FINANCE 登记付款/收款需选对手方:supplier/customer 列表须可读(此前 403 导致下拉恒空)。"""
    assert (await client.get("/api/v1/suppliers", headers=finance_headers)).status_code == 200
    assert (await client.get("/api/v1/customers", headers=finance_headers)).status_code == 200


# ---------- 附件下载强制改密门 ----------

@pytest.mark.asyncio
async def test_attachment_download_blocked_for_must_change_password(client, db_session):
    """must_change_password=True 的账号下载附件应被强制改密门拦(40007),与全仓非豁免端点一致。"""
    from app.services.user_service import create_internal_user
    email, pw = "mustchange@fulfillment.local", "MustChange123"
    await create_internal_user(
        db_session, email=email, name="待改密", password=pw, role="LOGISTICS",
        must_change_password=True, actor_user_id=0, actor_user_email="system@test")
    r = await client.post("/api/v1/auth/login", json={"identifier": email, "password": pw})
    assert r.status_code == 200, r.text
    token = r.json()["data"]["access_token"]
    resp = await client.get("/api/v1/attachments/1/download",
                            headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403 and resp.json()["code"] == 40007
