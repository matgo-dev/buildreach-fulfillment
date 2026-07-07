"""应用启动冒烟测试:依赖 T5 的 conftest(client fixture),本任务先写、
先跑不通(conftest 未就绪),T5 完成后统一转绿。
"""
import pytest


@pytest.mark.asyncio
async def test_healthz_ok(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"
