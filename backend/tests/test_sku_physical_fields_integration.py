import pytest


async def _seed_cat_unit(db):
    # "ton" 已由 app.seed._UNIT_SEEDS 全局种下(单一源头,见 conftest session-scope
    # run_all_seeds),此处仅需补品类;重复插入会撞 units_pkey 唯一约束。
    from app.db.models.category import Category
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "水泥"},
                    level=1, is_leaf=True, sort_order=0))
    await db.commit()


@pytest.mark.asyncio
async def test_create_sku_with_physical_and_masking(
        client, product_operator_headers, product_readonly_headers, db_session):
    await _seed_cat_unit(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=product_operator_headers, json={
        "category_code": "10", "name_i18n": {"zh": "海螺水泥"},
        "images": [{"image_key": "img/a.jpg", "image_type": "MAIN", "sort_order": 0}]})).json()["data"]["id"]

    r = await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": spu_id, "unit": "ton", "reference_price": 380.0, "name_i18n": {"zh": "吨装"},
        "weight_kg": 1000, "length_cm": 100, "width_cm": 80, "height_cm": 120,
        "spec_items": [], "images": []})
    assert r.status_code == 200, r.text
    sku_id = r.json()["data"]["id"]
    d = r.json()["data"]
    assert float(d["weight_kg"]) == 1000 and float(d["height_cm"]) == 120

    # 只读用户(仅 PRODUCT_READ):物理字段可见,reference_price 脱敏为 null
    dr = (await client.get(f"/api/v1/skus/{sku_id}", headers=product_readonly_headers)).json()["data"]
    assert dr["reference_price"] is None
    assert float(dr["weight_kg"]) == 1000 and float(dr["length_cm"]) == 100
