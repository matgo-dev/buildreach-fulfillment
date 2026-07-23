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
