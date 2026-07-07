"""附件上传关键路径集成测试:未认证拦截 + 认证后落盘返回 file_key。

测试环境用默认 STORAGE_BACKEND=local,不依赖 MinIO。
"""
import pytest


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    files = {"file": ("x.txt", b"hi", "text/plain")}
    r = await client.post("/api/v1/attachments", files=files)
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_upload_returns_file_key(client, superadmin_headers):
    files = {"file": ("x.txt", b"hi", "text/plain")}
    r = await client.post("/api/v1/attachments", files=files, headers=superadmin_headers)
    assert r.status_code == 200
    assert r.json()["data"]["file_key"].endswith("_x.txt")
