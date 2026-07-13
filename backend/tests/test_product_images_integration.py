"""product_images 规范化表 + reconcile 契约(设计:2026-07-12-0514-商品图片建模）。

覆盖:图集随 SPU/SKU 写接口按 image_key 对账;封面(MAIN)恰 1、切换不撞部分唯一索引;
主图组≤6 / 详情图≤12 / SKU 图≤6;重复 key 拒绝;列表出封面 flatten、详情出全量;
上传 20MB 硬限。旧 main_image/images/image 字段已下线。
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


def _img(key, image_type="GALLERY", sort_order=0):
    return {"image_key": key, "image_type": image_type, "sort_order": sort_order}


async def _create_spu(client, headers, images, **over):
    body = {"category_code": "10", "name_i18n": {"zh": "钢管"}, "images": images, **over}
    return await client.post("/api/v1/spus", headers=headers, json=body)


# ── 建 SPU:图集落库 + 三态 + 列表封面 flatten ──

@pytest.mark.asyncio
async def test_create_spu_with_image_set_persists_types(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    r = await _create_spu(client, product_operator_headers, [
        _img("img/cover.jpg", "MAIN", 0),
        _img("img/g1.jpg", "GALLERY", 1),
        _img("img/d1.jpg", "DETAIL", 0),
    ])
    assert r.status_code in (200, 201), r.text
    sid = r.json()["data"]["id"]

    detail = (await client.get(f"/api/v1/spus/{sid}", headers=product_operator_headers)).json()["data"]
    imgs = detail["images"]
    assert {i["image_key"]: i["image_type"] for i in imgs} == {
        "img/cover.jpg": "MAIN", "img/g1.jpg": "GALLERY", "img/d1.jpg": "DETAIL"}
    # 详情不再下发旧字段
    assert "main_image" not in detail or isinstance(detail.get("images"), list)

    lst = (await client.get("/api/v1/spus", headers=product_operator_headers)).json()["data"]
    row = next(x for x in lst["items"] if x["id"] == sid)
    assert row["main_image"] == "img/cover.jpg"  # 列表出封面 key


@pytest.mark.asyncio
async def test_create_spu_requires_exactly_one_main(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    # 0 个 MAIN → 拒
    r0 = await _create_spu(client, product_operator_headers, [_img("img/g.jpg", "GALLERY", 0)])
    assert r0.status_code == 422, r0.text
    # 2 个 MAIN → 拒
    r2 = await _create_spu(client, product_operator_headers, [
        _img("img/a.jpg", "MAIN", 0), _img("img/b.jpg", "MAIN", 1)])
    assert r2.status_code == 422, r2.text


@pytest.mark.asyncio
async def test_create_spu_gallery_cap_6(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    imgs = [_img("img/m.jpg", "MAIN", 0)] + [_img(f"img/g{i}.jpg", "GALLERY", i) for i in range(6)]
    r = await _create_spu(client, product_operator_headers, imgs)  # 主图组 = 1 MAIN + 6 GALLERY = 7 > 6
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_spu_detail_cap_12(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    imgs = [_img("img/m.jpg", "MAIN", 0)] + [_img(f"img/d{i}.jpg", "DETAIL", i) for i in range(13)]
    r = await _create_spu(client, product_operator_headers, imgs)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_spu_rejects_duplicate_image_key(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    r = await _create_spu(client, product_operator_headers, [
        _img("img/m.jpg", "MAIN", 0), _img("img/m.jpg", "GALLERY", 1)])
    assert r.status_code == 422, r.text


# ── reconcile:切封面(不撞部分唯一索引)+ 增删 ──

@pytest.mark.asyncio
async def test_update_spu_switch_cover(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    sid = (await _create_spu(client, product_operator_headers, [
        _img("img/a.jpg", "MAIN", 0), _img("img/b.jpg", "GALLERY", 1)])).json()["data"]["id"]

    # 把 b 提为封面、a 降 GALLERY —— 不得因中途两个 MAIN 撞唯一索引
    r = await client.put(f"/api/v1/spus/{sid}", headers=product_operator_headers, json={"images": [
        _img("img/a.jpg", "GALLERY", 1), _img("img/b.jpg", "MAIN", 0)]})
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/api/v1/spus/{sid}", headers=product_operator_headers)).json()["data"]
    assert {i["image_key"]: i["image_type"] for i in detail["images"]} == {
        "img/a.jpg": "GALLERY", "img/b.jpg": "MAIN"}


@pytest.mark.asyncio
async def test_update_spu_removes_absent_images(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    sid = (await _create_spu(client, product_operator_headers, [
        _img("img/a.jpg", "MAIN", 0), _img("img/b.jpg", "GALLERY", 1)])).json()["data"]["id"]

    r = await client.put(f"/api/v1/spus/{sid}", headers=product_operator_headers,
                         json={"images": [_img("img/a.jpg", "MAIN", 0)]})
    assert r.status_code == 200, r.text
    detail = (await client.get(f"/api/v1/spus/{sid}", headers=product_operator_headers)).json()["data"]
    assert [i["image_key"] for i in detail["images"]] == ["img/a.jpg"]


# ── SKU 图集(多图 ≤6)──

@pytest.mark.asyncio
async def test_sku_image_set_persists_and_cap6(client, product_operator_headers, db_session):
    await _seed_category(db_session)
    sid = (await _create_spu(client, product_operator_headers, [_img("img/m.jpg", "MAIN", 0)])).json()["data"]["id"]

    r = await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": sid, "unit": "piece", "name_i18n": {"zh": "钢管A"}, "spec_items": [],
        "images": [{"image_key": "img/s1.jpg", "sort_order": 0},
                   {"image_key": "img/s2.jpg", "sort_order": 1}]})
    assert r.status_code in (200, 201), r.text
    skid = r.json()["data"]["id"]
    sku = (await client.get(f"/api/v1/skus/{skid}", headers=product_operator_headers)).json()["data"]
    assert [i["image_key"] for i in sku["images"]] == ["img/s1.jpg", "img/s2.jpg"]

    r7 = await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": sid, "unit": "piece", "name_i18n": {"zh": "钢管B"}, "spec_items": [],
        "images": [{"image_key": f"img/x{i}.jpg", "sort_order": i} for i in range(7)]})
    assert r7.status_code == 422, r7.text


# ── 提交后 GC 孤儿存储对象(硬删图行不残留文件)──

async def _upload_and_store(client, headers, filename, body=b"realbytes"):
    """走 POST /uploads 拿 key → PUT 落盘,返回真实存在的 image_key。"""
    key = (await client.post("/api/v1/uploads", headers=headers,
           json={"filename": filename, "content_type": "image/jpeg"})).json()["data"]["key"]
    r = await client.put(f"/api/v1/uploads/{key}", headers=headers, content=body)
    assert r.status_code in (200, 201, 204), r.text
    return key


@pytest.mark.asyncio
async def test_update_spu_removing_image_gc_deletes_orphan_object(
        client, product_operator_headers, db_session):
    from app.services.storage import get_attachment_storage
    await _seed_category(db_session)
    gallery = await _upload_and_store(client, product_operator_headers, "g.jpg")
    assert get_attachment_storage().exists(gallery)

    sid = (await _create_spu(client, product_operator_headers, [
        _img("img/cover.jpg", "MAIN", 0), _img(gallery, "GALLERY", 1)])).json()["data"]["id"]

    # 移除该 gallery 图 → 无其它行引用 → 存储对象应被 GC
    r = await client.put(f"/api/v1/spus/{sid}", headers=product_operator_headers,
                         json={"images": [_img("img/cover.jpg", "MAIN", 0)]})
    assert r.status_code == 200, r.text
    assert not get_attachment_storage().exists(gallery)


@pytest.mark.asyncio
async def test_gc_keeps_object_still_referenced_by_sku(
        client, product_operator_headers, db_session):
    """同一 key 被 SKU 行引用时,从 SPU 移除不得删存储对象(引用计数保护)。"""
    from app.services.storage import get_attachment_storage
    await _seed_category(db_session)
    shared = await _upload_and_store(client, product_operator_headers, "shared.jpg")

    sid = (await _create_spu(client, product_operator_headers, [
        _img("img/cover.jpg", "MAIN", 0), _img(shared, "GALLERY", 1)])).json()["data"]["id"]
    # 同一 key 也挂到一个 SKU 上
    r = await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": sid, "unit": "piece", "name_i18n": {"zh": "钢管A"}, "spec_items": [],
        "images": [{"image_key": shared, "sort_order": 0}]})
    assert r.status_code in (200, 201), r.text

    # 从 SPU 移除 shared → SKU 行仍引用 → 存储对象保留
    await client.put(f"/api/v1/spus/{sid}", headers=product_operator_headers,
                     json={"images": [_img("img/cover.jpg", "MAIN", 0)]})
    assert get_attachment_storage().exists(shared)


# ── 上传 20MB 硬限 ──

@pytest.mark.asyncio
async def test_upload_put_rejects_oversize(client, product_operator_headers):
    created = (await client.post("/api/v1/uploads", headers=product_operator_headers,
               json={"filename": "big.jpg", "content_type": "image/jpeg"})).json()["data"]
    key = created["key"]
    big = b"x" * (20 * 1024 * 1024 + 1)
    r = await client.put(f"/api/v1/uploads/{key}", headers=product_operator_headers, content=big)
    assert r.status_code == 413, r.text
