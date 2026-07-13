import pytest


@pytest.mark.asyncio
async def test_spu_list_and_detail_carry_category_name(client, product_operator_headers, db_session):
    from app.db.models.category import Category
    db_session.add(Category(code="2336", parent_code=None, name_i18n={"zh": "水泥"},
                            level=1, is_leaf=True, sort_order=0))
    await db_session.commit()
    spu_id = (await client.post("/api/v1/spus", headers=product_operator_headers, json={
        "category_code": "2336", "name_i18n": {"zh": "海螺水泥"},
        "images": [{"image_key": "img/a.jpg", "image_type": "MAIN", "sort_order": 0}]})).json()["data"]["id"]

    lst = (await client.get("/api/v1/spus", headers=product_operator_headers)).json()["data"]["items"]
    assert lst[0]["category_name_i18n"]["zh"] == "水泥"
    det = (await client.get(f"/api/v1/spus/{spu_id}", headers=product_operator_headers)).json()["data"]
    assert det["category_name_i18n"]["zh"] == "水泥"
