import pytest
from sqlalchemy import select

from app.db.models.category import Category


async def _seed_category(db_session, code="10"):
    if not (await db_session.execute(
            select(Category).where(Category.code == code))).scalar_one_or_none():
        db_session.add(Category(code=code, parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()


@pytest.mark.asyncio
async def test_spu_crud_flow(client, product_operator_headers, db_session):
    h = product_operator_headers
    await _seed_category(db_session, "10")
    r = await client.post("/api/v1/spus", headers=h,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"},
                               "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r.status_code in (200, 201), r.text
    spu = r.json()["data"]
    assert spu["spu_code"].startswith("SPU")
    sid = spu["id"]

    # 详情:无 SKU 时 has_available_sku=False
    rd = await client.get(f"/api/v1/spus/{sid}", headers=h)
    assert rd.status_code == 200
    body = rd.json()["data"]
    assert body["has_available_sku"] is False
    assert body["skus"] == []

    # 列表
    r2 = await client.get("/api/v1/spus?keyword=钢", headers=h)
    assert r2.status_code == 200
    page = r2.json()["data"]
    assert page["total"] >= 1
    assert page["page"] == 1
    assert page["size"] == 20
    row = next(x for x in page["items"] if x["id"] == sid)
    assert row["has_available_sku"] is False

    # 改
    r_upd = await client.put(f"/api/v1/spus/{sid}", headers=h,
                             json={"name_i18n": {"zh": "钢管2"}})
    assert r_upd.status_code == 200, r_upd.text
    assert r_upd.json()["data"]["name_i18n"]["zh"] == "钢管2"

    # 上下架
    r3 = await client.patch(f"/api/v1/spus/{sid}/status", headers=h, json={"status": "INACTIVE"})
    assert r3.status_code == 200
    assert r3.json()["data"]["status"] == "INACTIVE"

    # 逻辑删 → 详情 404
    r4 = await client.delete(f"/api/v1/spus/{sid}", headers=h)
    assert r4.status_code in (200, 204)
    r5 = await client.get(f"/api/v1/spus/{sid}", headers=h)
    assert r5.status_code == 404


@pytest.mark.asyncio
async def test_spu_list_read_allowed_for_admin(client, superadmin_headers):
    r = await client.get("/api/v1/spus", headers=superadmin_headers)
    assert r.status_code == 200  # ADMIN 有 product:read


@pytest.mark.asyncio
async def test_spu_detail_cost_masked_for_read_only_role(client, superadmin_headers,
                                                          product_operator_headers, db_session):
    """详情内嵌 SKU 的 reference_price:PRODUCT_MANAGE 可见,仅 PRODUCT_READ 脱敏。"""
    await _seed_category(db_session, "10")
    r = await client.post("/api/v1/spus", headers=product_operator_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"},
                               "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})
    sid = r.json()["data"]["id"]
    r_sku = await client.post("/api/v1/skus", headers=product_operator_headers,
                              json={"spu_id": sid, "unit": "piece", "reference_price": "12.50",
                                    "name_i18n": {"zh": "钢管A"}, "spec_items": []})
    assert r_sku.status_code in (200, 201), r_sku.text

    # PRODUCT_MANAGE(operator)可见成本
    d_op = await client.get(f"/api/v1/spus/{sid}", headers=product_operator_headers)
    assert float(d_op.json()["data"]["skus"][0]["reference_price"]) == 12.50

    # 仅 PRODUCT_READ(admin)看不到成本(脱敏为 None)
    d_admin = await client.get(f"/api/v1/spus/{sid}", headers=superadmin_headers)
    assert d_admin.json()["data"]["skus"][0]["reference_price"] is None


@pytest.mark.asyncio
async def test_spu_derived_availability(client, product_operator_headers, db_session):
    """派生可用性:ACTIVE SKU → 可用;SPU 下架 → 不可用但 SKU.status 不级联变化。"""
    h = product_operator_headers
    await _seed_category(db_session, "10")
    r = await client.post("/api/v1/spus", headers=h,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"},
                               "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})
    sid = r.json()["data"]["id"]
    r_sku = await client.post("/api/v1/skus", headers=h,
                              json={"spu_id": sid, "unit": "piece", "reference_price": "1.00",
                                    "name_i18n": {"zh": "钢管A"}, "spec_items": []})
    skid = r_sku.json()["data"]["id"]

    d1 = await client.get(f"/api/v1/spus/{sid}", headers=h)
    b1 = d1.json()["data"]
    assert b1["has_available_sku"] is True
    sku1 = next(s for s in b1["skus"] if s["id"] == skid)
    assert sku1["available"] is True
    assert sku1["status"] == "ACTIVE"

    # 列表也带 has_available_sku=True
    lst1 = await client.get("/api/v1/spus?keyword=钢", headers=h)
    row1 = next(x for x in lst1.json()["data"]["items"] if x["id"] == sid)
    assert row1["has_available_sku"] is True

    # SPU 下架 → has_available_sku=False,SKU.available=False,但 SKU.status 不级联(仍 ACTIVE)
    await client.patch(f"/api/v1/spus/{sid}/status", headers=h, json={"status": "INACTIVE"})
    d2 = await client.get(f"/api/v1/spus/{sid}", headers=h)
    b2 = d2.json()["data"]
    assert b2["has_available_sku"] is False
    sku2 = next(s for s in b2["skus"] if s["id"] == skid)
    assert sku2["available"] is False
    assert sku2["status"] == "ACTIVE"  # 不级联

    lst2 = await client.get("/api/v1/spus?keyword=钢", headers=h)
    row2 = next(x for x in lst2.json()["data"]["items"] if x["id"] == sid)
    assert row2["has_available_sku"] is False

    # SPU 恢复上架 + SKU 自身下架(走 PATCH /skus/{id}/status 端点)→ available=False(SKU 侧原因)
    await client.patch(f"/api/v1/spus/{sid}/status", headers=h, json={"status": "ACTIVE"})
    await client.patch(f"/api/v1/skus/{skid}/status", headers=h, json={"status": "INACTIVE"})

    d3 = await client.get(f"/api/v1/spus/{sid}", headers=h)
    b3 = d3.json()["data"]
    assert b3["has_available_sku"] is False
    sku3 = next(s for s in b3["skus"] if s["id"] == skid)
    assert sku3["available"] is False
    assert sku3["status"] == "INACTIVE"


@pytest.mark.asyncio
async def test_spus_category_subtree_filter(client, product_operator_headers, db_session):
    """品类子树前缀过滤:选父类含子孙 SPU;include_descendants=false 仅本级;前缀不误匹配兄弟。"""
    h = product_operator_headers
    # 建材(01) → 水泥(01.001) → 硅酸盐水泥(01.001.001,叶子);另建五金(02,叶子),前缀边界用。
    db_session.add_all([
        Category(code="01", parent_code=None, name_i18n={"zh": "建材"},
                 level=1, is_leaf=False, sort_order=0),
        Category(code="01.001", parent_code="01", name_i18n={"zh": "水泥"},
                 level=2, is_leaf=False, sort_order=0),
        Category(code="01.001.001", parent_code="01.001", name_i18n={"zh": "硅酸盐水泥"},
                 level=3, is_leaf=True, sort_order=0),
        Category(code="02", parent_code=None, name_i18n={"zh": "五金"},
                 level=1, is_leaf=True, sort_order=0),
    ])
    await db_session.commit()

    r_a = await client.post("/api/v1/spus", headers=h,
                            json={"category_code": "01.001.001", "name_i18n": {"zh": "水泥A"},
                                 "images": [{"image_key": "img/a.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r_a.status_code in (200, 201), r_a.text
    spu_a_id = r_a.json()["data"]["id"]

    r_b = await client.post("/api/v1/spus", headers=h,
                            json={"category_code": "02", "name_i18n": {"zh": "五金B"},
                                 "images": [{"image_key": "img/b.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r_b.status_code in (200, 201), r_b.text
    spu_b_id = r_b.json()["data"]["id"]

    # 选父类 01(含子树,默认) → 含 SPU_A
    r1 = await client.get("/api/v1/spus?category_code=01", headers=h)
    assert r1.status_code == 200
    ids1 = {x["id"] for x in r1.json()["data"]["items"]}
    assert spu_a_id in ids1
    assert spu_b_id not in ids1

    # 01 + include_descendants=false → 01 无直接挂载,不含 SPU_A
    r2 = await client.get("/api/v1/spus?category_code=01&include_descendants=false", headers=h)
    assert r2.status_code == 200
    ids2 = {x["id"] for x in r2.json()["data"]["items"]}
    assert spu_a_id not in ids2

    # 精确叶子命中
    r3 = await client.get("/api/v1/spus?category_code=01.001.001", headers=h)
    assert r3.status_code == 200
    ids3 = {x["id"] for x in r3.json()["data"]["items"]}
    assert spu_a_id in ids3

    # 前缀边界:02 不误含 01 子树
    r4 = await client.get("/api/v1/spus?category_code=02", headers=h)
    assert r4.status_code == 200
    ids4 = {x["id"] for x in r4.json()["data"]["items"]}
    assert spu_a_id not in ids4
    assert spu_b_id in ids4


@pytest.mark.asyncio
async def test_spus_category_subtree_filter_escapes_like_wildcards(client, product_operator_headers,
                                                                     db_session):
    """category_code 含 LIKE 元字符(%)时不当通配符解释:转义前会把 01.001 误吸进 '0%' 的结果。"""
    h = product_operator_headers
    db_session.add_all([
        Category(code="01", parent_code=None, name_i18n={"zh": "建材"},
                 level=1, is_leaf=False, sort_order=0),
        Category(code="01.001", parent_code="01", name_i18n={"zh": "水泥"},
                 level=2, is_leaf=True, sort_order=0),
    ])
    await db_session.commit()

    r_a = await client.post("/api/v1/spus", headers=h,
                            json={"category_code": "01.001", "name_i18n": {"zh": "水泥A"},
                                 "images": [{"image_key": "img/a.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r_a.status_code in (200, 201), r_a.text
    spu_a_id = r_a.json()["data"]["id"]

    # "0%" 若未转义会被当"0 后跟任意字符"的通配符,误把 01.001 吸进来;
    # 转义生效后应等价于精确查找 code="0%" 的品类(不存在)→ 不含 SPU_A。
    r = await client.get("/api/v1/spus", params={"category_code": "0%"}, headers=h)
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()["data"]["items"]}
    assert spu_a_id not in ids


@pytest.mark.asyncio
async def test_spus_category_subtree_filter_variable_length_prefix_boundary(
        client, product_operator_headers, db_session):
    """变长同前缀边界:01 与 010 是两个独立顶级分类,查 01 不应吸入挂在 010 下的 SPU。"""
    h = product_operator_headers
    db_session.add_all([
        Category(code="01", parent_code=None, name_i18n={"zh": "建材"},
                 level=1, is_leaf=True, sort_order=0),
        Category(code="010", parent_code=None, name_i18n={"zh": "建材配件"},
                 level=1, is_leaf=True, sort_order=0),
    ])
    await db_session.commit()

    r_a = await client.post("/api/v1/spus", headers=h,
                            json={"category_code": "01", "name_i18n": {"zh": "水泥A"},
                                 "images": [{"image_key": "img/a.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r_a.status_code in (200, 201), r_a.text
    spu_a_id = r_a.json()["data"]["id"]

    r_b = await client.post("/api/v1/spus", headers=h,
                            json={"category_code": "010", "name_i18n": {"zh": "配件B"},
                                 "images": [{"image_key": "img/b.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r_b.status_code in (200, 201), r_b.text
    spu_b_id = r_b.json()["data"]["id"]

    r = await client.get("/api/v1/spus?category_code=01", headers=h)
    assert r.status_code == 200
    ids = {x["id"] for x in r.json()["data"]["items"]}
    assert spu_a_id in ids
    assert spu_b_id not in ids
