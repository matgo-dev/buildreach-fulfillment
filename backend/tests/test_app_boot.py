"""应用启动冒烟测试:依赖 T5 的 conftest(client fixture),本任务先写、
先跑不通(conftest 未就绪),T5 完成后统一转绿。
"""
import pytest


@pytest.mark.asyncio
async def test_healthz_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


@pytest.mark.asyncio
async def test_version_public_ok(client):
    """无鉴权可达;本地无 BUILD_* 注入时 commit 兜底 dev(注入链见 deploy README)。"""
    r = await client.get("/api/v1/version")
    assert r.status_code == 200
    data = r.json()["data"]
    assert set(data) == {"commit", "branch", "author", "commit_time", "build_time"}
    assert data["commit"] == "dev"


@pytest.mark.asyncio
async def test_request_envelope_headers(client):
    """每个响应带 trace 头与耗时头(耗时观测:供事后按 trace 定位慢请求)。"""
    r = await client.get("/healthz")
    assert r.headers.get("X-Trace-Id")
    # 形如 "1.2";可解析为非负浮点
    assert float(r.headers["X-Process-Time-Ms"]) >= 0


@pytest.mark.asyncio
async def test_access_log_skips_healthz(client, caplog):
    """访问日志落业务请求、跳过 /healthz 高频探针(避免刷屏)。"""
    import logging

    with caplog.at_level(logging.INFO, logger="app.request"):
        await client.get("/healthz")
        await client.get("/api/v1/version")
    lines = [rec.getMessage() for rec in caplog.records if rec.name == "app.request"]
    assert any("/api/v1/version" in m for m in lines)
    assert not any("/healthz" in m for m in lines)
