"""商品图片(spec §9):main_image 必填、images/sku.image 落库、
上传端点契约(POST /uploads、PUT /uploads/{key})、权限门。
"""
import pytest
from sqlalchemy import select

from app.db.models.category import Category


async def _seed_category(db_session, code="10"):
    if not (await db_session.execute(
            select(Category).where(Category.code == code))).scalar_one_or_none():
        db_session.add(Category(code=code, parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()


# ── main_image 必填(SpuCreateIn 非空校验) ──

@pytest.mark.asyncio
async def test_create_spu_without_main_image_422(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    r = await client.post("/api/v1/spus", headers=catalog_operator_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_spu_with_blank_main_image_422(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    r = await client.post("/api/v1/spus", headers=catalog_operator_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"},
                               "main_image": "   "})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_spu_with_main_image_and_images_persists(
    client, catalog_operator_headers, db_session
):
    await _seed_category(db_session)
    r = await client.post("/api/v1/spus", headers=catalog_operator_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"},
                               "main_image": "img/main.jpg", "images": ["img/a.jpg", "img/b.jpg"]})
    assert r.status_code in (200, 201), r.text
    data = r.json()["data"]
    assert data["main_image"] == "img/main.jpg"
    assert data["images"] == ["img/a.jpg", "img/b.jpg"]


@pytest.mark.asyncio
async def test_update_spu_main_image(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    r = await client.post("/api/v1/spus", headers=catalog_operator_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"},
                               "main_image": "img/old.jpg"})
    sid = r.json()["data"]["id"]
    r2 = await client.put(f"/api/v1/spus/{sid}", headers=catalog_operator_headers,
                          json={"main_image": "img/new.jpg"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["main_image"] == "img/new.jpg"


@pytest.mark.asyncio
async def test_update_spu_main_image_blank_rejected(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    r = await client.post("/api/v1/spus", headers=catalog_operator_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"},
                               "main_image": "img/old.jpg"})
    sid = r.json()["data"]["id"]
    r2 = await client.put(f"/api/v1/spus/{sid}", headers=catalog_operator_headers,
                          json={"main_image": ""})
    assert r2.status_code == 422


# ── SkuOut.image + 回退字段 spu_main_image ──

@pytest.mark.asyncio
async def test_sku_out_has_image_field_and_falls_back_to_spu_main_image(
    client, catalog_operator_headers, db_session
):
    await _seed_category(db_session)
    spu = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
        json={"category_code": "10", "name_i18n": {"zh": "钢管"},
             "main_image": "img/spu-main.jpg"})).json()["data"]

    # SKU 不带图 → SkuOut.image=None,spu_main_image 回退可用
    r_sku = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu["id"], "unit": "piece", "name_i18n": {"zh": "钢管A"}, "spec_items": []})
    assert r_sku.status_code in (200, 201), r_sku.text
    assert r_sku.json()["data"]["image"] is None

    r_search = await client.get(f"/api/v1/skus?spu_id={spu['id']}",
                                headers=catalog_operator_headers)
    row = r_search.json()["data"]["items"][0]
    assert row["image"] is None
    assert row["spu_main_image"] == "img/spu-main.jpg"

    # SKU 自带图 → 搜索行 image 生效(前端 sku.image ?? spu_main_image 取到 SKU 自己的)
    r_sku2 = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu["id"], "unit": "piece", "name_i18n": {"zh": "钢管B"}, "spec_items": [],
        "image": "img/sku-b.jpg"})
    assert r_sku2.json()["data"]["image"] == "img/sku-b.jpg"

    r_search2 = await client.get(f"/api/v1/skus?spu_id={spu['id']}",
                                 headers=catalog_operator_headers)
    row2 = next(x for x in r_search2.json()["data"]["items"]
                if x["name_i18n"]["zh"] == "钢管B")
    assert row2["image"] == "img/sku-b.jpg"
    assert row2["spu_main_image"] == "img/spu-main.jpg"


@pytest.mark.asyncio
async def test_update_sku_image(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
        json={"category_code": "10", "name_i18n": {"zh": "钢管"},
             "main_image": "img/spu-main.jpg"})).json()["data"]
    sku = (await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu["id"], "unit": "piece", "name_i18n": {"zh": "钢管A"},
        "spec_items": []})).json()["data"]

    r = await client.put(f"/api/v1/skus/{sku['id']}", headers=catalog_operator_headers,
                         json={"image": "img/updated.jpg"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["image"] == "img/updated.jpg"


# ── 上传端点契约(local 后端,默认 STORAGE_BACKEND) ──

@pytest.mark.asyncio
async def test_create_upload_returns_key_url_method(client, catalog_operator_headers):
    r = await client.post("/api/v1/uploads", headers=catalog_operator_headers,
                          json={"filename": "photo.jpg", "content_type": "image/jpeg"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert set(data) == {"key", "upload_url", "method"}
    assert data["method"] == "PUT"
    assert data["key"].startswith("img/")
    assert data["key"].endswith("_photo.jpg")
    assert data["upload_url"] == f"/api/v1/uploads/{data['key']}"


@pytest.mark.asyncio
async def test_create_upload_requires_manage_permission(client, superadmin_headers):
    # ADMIN 有 catalog:read 无 catalog:manage → 403(能改商品才能传图)
    r = await client.post("/api/v1/uploads", headers=superadmin_headers,
                          json={"filename": "photo.jpg", "content_type": "image/jpeg"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_put_upload_local_backend_receives_and_persists(client, catalog_operator_headers):
    created = (await client.post("/api/v1/uploads", headers=catalog_operator_headers,
               json={"filename": "photo.jpg", "content_type": "image/jpeg"})).json()["data"]
    key = created["key"]

    r = await client.put(f"/api/v1/uploads/{key}", headers=catalog_operator_headers,
                         content=b"fake-image-bytes")
    assert r.status_code == 200, r.text

    from app.services.storage import get_attachment_storage
    storage = get_attachment_storage()
    assert storage.exists(key)
    assert storage.open(key).read() == b"fake-image-bytes"
    storage.delete(key)


@pytest.mark.asyncio
async def test_put_upload_requires_manage_permission(client, superadmin_headers):
    r = await client.put("/api/v1/uploads/img/whatever.jpg", headers=superadmin_headers,
                         content=b"x")
    assert r.status_code == 403


# ── 安全加固:key 形状校验 + content-type 白名单(防越权覆盖/存储型 XSS) ──

from app.api.v1.uploads import _KEY_RE  # noqa: E402


@pytest.mark.asyncio
async def test_create_upload_rejects_svg_content_type(client, catalog_operator_headers):
    r = await client.post("/api/v1/uploads", headers=catalog_operator_headers,
                          json={"filename": "evil.svg", "content_type": "image/svg+xml"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_upload_rejects_non_image_content_type(client, catalog_operator_headers):
    r = await client.post("/api/v1/uploads", headers=catalog_operator_headers,
                          json={"filename": "evil.html", "content_type": "text/html"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_upload_accepts_png_and_key_matches_shape(client, catalog_operator_headers):
    r = await client.post("/api/v1/uploads", headers=catalog_operator_headers,
                          json={"filename": "photo.png", "content_type": "image/png"})
    assert r.status_code == 200, r.text
    key = r.json()["data"]["key"]
    assert _KEY_RE.fullmatch(key)


@pytest.mark.asyncio
async def test_create_upload_sanitizes_chinese_and_space_filename(client, catalog_operator_headers):
    r = await client.post("/api/v1/uploads", headers=catalog_operator_headers,
                          json={"filename": "商品 图片 中文名.png", "content_type": "image/png"})
    assert r.status_code == 200, r.text
    key = r.json()["data"]["key"]
    assert _KEY_RE.fullmatch(key), key


@pytest.mark.asyncio
async def test_put_upload_rejects_path_traversal_key(client, catalog_operator_headers):
    r = await client.put("/api/v1/uploads/../../etc/passwd", headers=catalog_operator_headers,
                         content=b"x")
    # httpx 在构造请求 URL 时会先按 RFC3986 折叠 ".." 段(落到 /api/etc/passwd,不再匹配
    # /api/v1/uploads 前缀)→ 404;若某客户端不折叠而是原样送达,则落进 _KEY_RE 校验 → 400。
    # 两种结果都意味着 200/写入未发生 —— 穿越不可达。
    assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_put_upload_rejects_encoded_path_traversal_key(client, catalog_operator_headers):
    r = await client.put("/api/v1/uploads/..%2F..%2Fx", headers=catalog_operator_headers,
                         content=b"x")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_upload_rejects_arbitrary_preexisting_key(client, catalog_operator_headers):
    # 非 create_upload 生成形状的 key(如覆盖既有商品图)一律拒绝
    r = await client.put("/api/v1/uploads/img/main.jpg", headers=catalog_operator_headers,
                         content=b"x")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_upload_accepts_valid_generated_key(client, catalog_operator_headers):
    created = (await client.post("/api/v1/uploads", headers=catalog_operator_headers,
               json={"filename": "photo.png", "content_type": "image/png"})).json()["data"]
    key = created["key"]

    r = await client.put(f"/api/v1/uploads/{key}", headers=catalog_operator_headers,
                         content=b"fake-image-bytes")
    assert r.status_code == 200, r.text

    from app.services.storage import get_attachment_storage
    storage = get_attachment_storage()
    assert storage.exists(key)
    storage.delete(key)
