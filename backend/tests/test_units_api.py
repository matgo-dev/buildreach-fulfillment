"""units 售卖单位专表(spec §11 Part A):GET /units 下拉数据 + FK RESTRICT 删检查。"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.unit import Unit


@pytest.mark.asyncio
async def test_units_list_requires_read(client):
    assert (await client.get("/api/v1/units")).status_code == 401


@pytest.mark.asyncio
async def test_units_list_ok_and_shape(client, product_readonly_headers):
    r = await client.get("/api/v1/units", headers=product_readonly_headers)
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert isinstance(items, list) and len(items) > 0
    assert {"code", "label_i18n", "sort_order"} == set(items[0].keys())
    codes = {i["code"] for i in items}
    assert "piece" in codes


@pytest.mark.asyncio
async def test_units_list_excludes_inactive(client, product_readonly_headers, db_session):
    db_session.add(Unit(code="deprecated_unit", label_i18n={"zh": "废弃单位"},
                        sort_order=999, is_active=False))
    await db_session.commit()
    r = await client.get("/api/v1/units", headers=product_readonly_headers)
    codes = {i["code"] for i in r.json()["data"]["items"]}
    assert "deprecated_unit" not in codes


@pytest.mark.asyncio
async def test_sku_unit_fk_restrict_blocks_delete(
    client, product_operator_headers, db_session
):
    """在用单位(有 SKU 引用)FK ON DELETE RESTRICT 挡住物理删除。"""
    from app.db.models.category import Category

    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    spu = (await client.post("/api/v1/spus", headers=product_operator_headers,
        json={"category_code": "10", "name_i18n": {"zh": "钢管"},
             "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})).json()["data"]
    r_sku = await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": spu["id"], "unit": "piece", "name_i18n": {"zh": "钢管A"}, "spec_items": []})
    assert r_sku.status_code in (200, 201), r_sku.text

    unit = (await db_session.execute(select(Unit).where(Unit.code == "piece"))).scalar_one()
    await db_session.delete(unit)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_create_sku_rejects_unknown_unit_code(
    client, product_operator_headers, db_session
):
    from app.db.models.category import Category

    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    spu = (await client.post("/api/v1/spus", headers=product_operator_headers,
        json={"category_code": "10", "name_i18n": {"zh": "钢管"},
             "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})).json()["data"]
    r = await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": spu["id"], "unit": "not_a_real_unit", "name_i18n": {"zh": "钢管A"},
        "spec_items": []})
    assert r.status_code == 404, r.text
