import pytest


async def _seed_cat(db):
    from app.db.models.category import Category
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "水泥"},
                    level=1, is_leaf=True, sort_order=0))
    await db.commit()


@pytest.mark.asyncio
async def test_create_and_read_spu_with_master_fields(client, product_operator_headers, db_session):
    await _seed_cat(db_session)
    r = await client.post("/api/v1/spus", headers=product_operator_headers, json={
        "category_code": "10", "name_i18n": {"zh": "海螺水泥"},
        "brand": "海螺", "description": "42.5 普通硅酸盐", "hs_code": "2523290000",
        "images": [{"image_key": "img/a.jpg", "image_type": "MAIN", "sort_order": 0}]})
    assert r.status_code == 200, r.text
    spu_id = r.json()["data"]["id"]

    d = (await client.get(f"/api/v1/spus/{spu_id}", headers=product_operator_headers)).json()["data"]
    assert d["brand"] == "海螺" and d["hs_code"] == "2523290000" and d["description"] == "42.5 普通硅酸盐"

    r2 = await client.put(f"/api/v1/spus/{spu_id}", headers=product_operator_headers,
                          json={"brand": "华润", "hs_code": "2523900000"})
    assert r2.status_code == 200, r2.text
    d2 = (await client.get(f"/api/v1/spus/{spu_id}", headers=product_operator_headers)).json()["data"]
    assert d2["brand"] == "华润" and d2["hs_code"] == "2523900000"
