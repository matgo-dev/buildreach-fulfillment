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


@pytest.mark.asyncio
async def test_upload_sanitizes_path_in_filename(client, superadmin_headers):
    """恶意文件名带路径段时,file_key 必须被剥成纯 basename,防注入存储 key 命名空间。"""
    files = {"file": ("../../evil.txt", b"x", "text/plain")}
    r = await client.post("/api/v1/attachments", files=files, headers=superadmin_headers)
    assert r.status_code == 200
    key = r.json()["data"]["file_key"]
    assert "/" not in key and ".." not in key
    assert key.endswith("_evil.txt")
