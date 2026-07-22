"""图片上传端点契约(POST /uploads、PUT /uploads/{key})+ 安全加固 + /media 本地读取。

商品图与 SPU/SKU 的关联(main/gallery/detail/SKU 图)已规范化到 product_images 表,
其契约见 test_product_images_integration.py;本文件只覆盖存储直传端点本身与读取。
"""
import pytest

from app.api.v1.uploads import _KEY_RE


# ── 上传端点契约(local 后端,默认 STORAGE_BACKEND) ──

@pytest.mark.asyncio
async def test_create_upload_returns_key_url_method(client, product_operator_headers):
    r = await client.post("/api/v1/uploads", headers=product_operator_headers,
                          json={"filename": "photo.jpg", "content_type": "image/jpeg"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert set(data) == {"key", "upload_url", "method"}
    assert data["method"] == "PUT"
    assert data["key"].startswith("img/")
    assert data["key"].endswith("_photo.jpg")
    assert data["upload_url"] == f"/api/v1/uploads/{data['key']}"


@pytest.mark.asyncio
async def test_create_upload_requires_manage_permission(client, product_readonly_headers):
    # 只读角色无 product:manage → 403(能改商品才能传图)
    r = await client.post("/api/v1/uploads", headers=product_readonly_headers,
                          json={"filename": "photo.jpg", "content_type": "image/jpeg"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_put_upload_local_backend_receives_and_persists(client, product_operator_headers):
    created = (await client.post("/api/v1/uploads", headers=product_operator_headers,
               json={"filename": "photo.jpg", "content_type": "image/jpeg"})).json()["data"]
    key = created["key"]

    r = await client.put(f"/api/v1/uploads/{key}", headers=product_operator_headers,
                         content=b"fake-image-bytes")
    assert r.status_code == 200, r.text

    from app.services.storage import get_attachment_storage
    storage = get_attachment_storage()
    assert storage.exists(key)
    assert storage.open(key).read() == b"fake-image-bytes"
    storage.delete(key)


@pytest.mark.asyncio
async def test_put_upload_requires_manage_permission(client, product_readonly_headers):
    r = await client.put("/api/v1/uploads/img/whatever.jpg", headers=product_readonly_headers,
                         content=b"x")
    assert r.status_code == 403


# ── 安全加固:key 形状校验 + content-type 白名单(防越权覆盖/存储型 XSS) ──

@pytest.mark.asyncio
async def test_create_upload_rejects_svg_content_type(client, product_operator_headers):
    r = await client.post("/api/v1/uploads", headers=product_operator_headers,
                          json={"filename": "evil.svg", "content_type": "image/svg+xml"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_upload_rejects_non_image_content_type(client, product_operator_headers):
    r = await client.post("/api/v1/uploads", headers=product_operator_headers,
                          json={"filename": "evil.html", "content_type": "text/html"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_upload_accepts_png_and_key_matches_shape(client, product_operator_headers):
    r = await client.post("/api/v1/uploads", headers=product_operator_headers,
                          json={"filename": "photo.png", "content_type": "image/png"})
    assert r.status_code == 200, r.text
    key = r.json()["data"]["key"]
    assert _KEY_RE.fullmatch(key)


@pytest.mark.asyncio
async def test_create_upload_sanitizes_chinese_and_space_filename(client, product_operator_headers):
    r = await client.post("/api/v1/uploads", headers=product_operator_headers,
                          json={"filename": "商品 图片 中文名.png", "content_type": "image/png"})
    assert r.status_code == 200, r.text
    key = r.json()["data"]["key"]
    assert _KEY_RE.fullmatch(key), key


@pytest.mark.asyncio
async def test_put_upload_rejects_path_traversal_key(client, product_operator_headers):
    r = await client.put("/api/v1/uploads/../../etc/passwd", headers=product_operator_headers,
                         content=b"x")
    assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_put_upload_rejects_encoded_path_traversal_key(client, product_operator_headers):
    r = await client.put("/api/v1/uploads/..%2F..%2Fx", headers=product_operator_headers,
                         content=b"x")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_upload_rejects_arbitrary_preexisting_key(client, product_operator_headers):
    r = await client.put("/api/v1/uploads/img/main.jpg", headers=product_operator_headers,
                         content=b"x")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_upload_accepts_valid_generated_key(client, product_operator_headers):
    created = (await client.post("/api/v1/uploads", headers=product_operator_headers,
               json={"filename": "photo.png", "content_type": "image/png"})).json()["data"]
    key = created["key"]

    r = await client.put(f"/api/v1/uploads/{key}", headers=product_operator_headers,
                         content=b"fake-image-bytes")
    assert r.status_code == 200, r.text

    from app.services.storage import get_attachment_storage
    storage = get_attachment_storage()
    assert storage.exists(key)
    storage.delete(key)


# ── /media 本地读取:build_url 返回的 /media/{key} 现可服务(前端 <img> 无需鉴权)──

@pytest.mark.asyncio
async def test_media_get_serves_uploaded_local_image(client, product_operator_headers):
    created = (await client.post("/api/v1/uploads", headers=product_operator_headers,
               json={"filename": "photo.png", "content_type": "image/png"})).json()["data"]
    key = created["key"]
    await client.put(f"/api/v1/uploads/{key}", headers=product_operator_headers,
                     content=b"PNGDATA")

    r = await client.get(f"/media/{key}")
    assert r.status_code == 200, r.text
    assert r.content == b"PNGDATA"
    assert r.headers["content-type"].startswith("image/png")

    from app.services.storage import get_attachment_storage
    get_attachment_storage().delete(key)


@pytest.mark.asyncio
async def test_media_get_missing_key_404(client):
    r = await client.get("/media/img/00000000000000000000000000000000_absent.png")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_media_get_rejects_bad_key_shape(client):
    r = await client.get("/media/img/../../etc/passwd")
    assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_media_get_serves_via_object_storage_backend(client, monkeypatch):
    """s3 后端下 /media 由后端代理对象存储(私有桶也可读),不再一律 404。"""
    from io import BytesIO
    import app.api.media as media_mod

    class _FakeStorage:
        def exists(self, key: str) -> bool:
            return True

        def open(self, key: str):
            return BytesIO(b"S3BYTES")

    monkeypatch.setattr(media_mod, "get_attachment_storage", lambda: _FakeStorage())
    r = await client.get("/media/img/00000000000000000000000000000000_x.png")
    assert r.status_code == 200, r.text
    assert r.content == b"S3BYTES"
