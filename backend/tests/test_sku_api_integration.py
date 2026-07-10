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
async def test_sku_flow_and_cost_redaction(client, catalog_operator_headers, superadmin_headers,
                                           db_session):
    h = catalog_operator_headers
    await _seed_category(db_session, "10")
    spu = (await client.post("/api/v1/spus", headers=h,
        json={"category_code": "10", "name_i18n": {"zh": "钢管"}})).json()["data"]
    r = await client.post("/api/v1/skus", headers=h, json={
        "spu_id": spu["id"], "unit": "PCS", "reference_price": "12.50",
        "name_i18n": {"zh": "钢管DN50"}, "spec_items": []})
    assert r.status_code in (200, 201), r.text
    sku = r.json()["data"]
    assert sku["reference_price"] in ("12.50", 12.5)

    # ADMIN(仅 read)读该 SKU → reference_price 脱敏为 null
    rid = sku["id"]
    r2 = await client.get(f"/api/v1/skus/{rid}", headers=superadmin_headers)
    assert r2.status_code == 200
    assert r2.json()["data"]["reference_price"] is None

    # 上下架 + 逻辑删
    assert (await client.patch(f"/api/v1/skus/{rid}/status", headers=h,
            json={"status": "INACTIVE"})).status_code == 200
    assert (await client.delete(f"/api/v1/skus/{rid}", headers=h)).status_code in (200, 204)
    assert (await client.get(f"/api/v1/skus/{rid}", headers=h)).status_code == 404


@pytest.mark.asyncio
async def test_admin_cannot_create_sku(client, superadmin_headers):
    r = await client.post("/api/v1/skus", headers=superadmin_headers, json={
        "spu_id": 1, "unit": "PCS", "name_i18n": {"zh": "x"}, "spec_items": []})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_search_cost_redaction_and_pagination(client, catalog_operator_headers,
                                                     superadmin_headers, db_session):
    h = catalog_operator_headers
    await _seed_category(db_session, "10")
    spu = (await client.post("/api/v1/spus", headers=h,
        json={"category_code": "10", "name_i18n": {"zh": "阀门XYZ"}})).json()["data"]
    await client.post("/api/v1/skus", headers=h, json={
        "spu_id": spu["id"], "unit": "PCS", "reference_price": "9.99",
        "name_i18n": {"zh": "阀门XYZ-A"}, "spec_items": []})

    r_op = await client.get("/api/v1/skus?q=阀门XYZ", headers=h)
    assert r_op.status_code == 200
    body_op = r_op.json()["data"]
    assert body_op["total"] >= 1
    assert body_op["page"] == 1
    assert body_op["size"] == 20
    row_op = next(x for x in body_op["items"] if x["name_i18n"]["zh"] == "阀门XYZ-A")
    assert row_op["reference_price"] in ("9.99", 9.99)

    r_admin = await client.get("/api/v1/skus?q=阀门XYZ", headers=superadmin_headers)
    assert r_admin.status_code == 200
    row_admin = next(x for x in r_admin.json()["data"]["items"]
                      if x["name_i18n"]["zh"] == "阀门XYZ-A")
    assert row_admin["reference_price"] is None


@pytest.mark.asyncio
async def test_search_spu_id_filter(client, catalog_operator_headers, db_session):
    h = catalog_operator_headers
    await _seed_category(db_session, "10")
    spu1 = (await client.post("/api/v1/spus", headers=h,
        json={"category_code": "10", "name_i18n": {"zh": "SPU甲"}})).json()["data"]
    spu2 = (await client.post("/api/v1/spus", headers=h,
        json={"category_code": "10", "name_i18n": {"zh": "SPU乙"}})).json()["data"]
    await client.post("/api/v1/skus", headers=h, json={
        "spu_id": spu1["id"], "unit": "PCS", "name_i18n": {"zh": "甲SKU"}, "spec_items": []})
    await client.post("/api/v1/skus", headers=h, json={
        "spu_id": spu2["id"], "unit": "PCS", "name_i18n": {"zh": "乙SKU"}, "spec_items": []})

    r = await client.get(f"/api/v1/skus?spu_id={spu1['id']}", headers=h)
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert all(i["spu_id"] == spu1["id"] for i in items)
    assert any(i["name_i18n"]["zh"] == "甲SKU" for i in items)
    assert not any(i["name_i18n"]["zh"] == "乙SKU" for i in items)


@pytest.mark.asyncio
async def test_search_available_filter_cascades_on_spu_status(client, catalog_operator_headers,
                                                               db_session):
    """available=1:SPU/SKU 均 ACTIVE 才命中;SPU 下架后不再命中;available=0(默认)仍命中。"""
    h = catalog_operator_headers
    await _seed_category(db_session, "10")
    spu = (await client.post("/api/v1/spus", headers=h,
        json={"category_code": "10", "name_i18n": {"zh": "钢丝网"}})).json()["data"]
    await client.post("/api/v1/skus", headers=h, json={
        "spu_id": spu["id"], "unit": "PCS", "name_i18n": {"zh": "钢丝网A"}, "spec_items": []})

    r1 = await client.get("/api/v1/skus?q=钢丝&available=1", headers=h)
    assert r1.status_code == 200
    assert r1.json()["data"]["total"] >= 1

    await client.patch(f"/api/v1/spus/{spu['id']}/status", headers=h,
                       json={"status": "INACTIVE"})

    r2 = await client.get("/api/v1/skus?q=钢丝&available=1", headers=h)
    assert r2.json()["data"]["total"] == 0

    r3 = await client.get("/api/v1/skus?q=钢丝&available=0", headers=h)
    assert r3.json()["data"]["total"] >= 1
