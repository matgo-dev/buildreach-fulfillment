import pytest
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.sku import Sku
from app.services import spec_template_service as tmpl


async def _seed_category(db_session, code="10"):
    db_session.add(Category(code=code, parent_code=None, name_i18n={"zh": "阀门"},
                            level=1, is_leaf=True, sort_order=0))
    await db_session.commit()


@pytest.mark.asyncio
async def test_create_spu_then_sku_builds_search_text(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)

    r_spu = await client.post("/api/v1/spus", headers=catalog_operator_headers,
                              json={"category_code": "10", "name_i18n": {"zh": "球阀"}})
    assert r_spu.status_code == 200, r_spu.text
    spu_id = r_spu.json()["data"]["id"]

    r_sku = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "PCS", "reference_price": 128.0,
        "name_i18n": {"zh": "不锈钢球阀 DN50"},
        "spec_items": [
            {"key": "dn", "value": "DN50"},
            {"key": "coating", "value": {"zh": "喷塑"}, "label_i18n": {"zh": "涂层"}},
        ],
    })
    assert r_sku.status_code == 200, r_sku.text
    sku_id = r_sku.json()["data"]["id"]
    assert r_sku.json()["data"]["sku_code"].startswith("SKU")

    row = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    for token in ["不锈钢球阀 DN50", "DN50", "喷塑"]:
        assert token in row.search_text

    # 手输 key 'coating' 已即时回写模板(source=运营手加)
    by_key = await tmpl.suggestions_by_key(db_session, "10")
    assert by_key["coating"]["source"] == "运营手加"


@pytest.mark.asyncio
async def test_update_sku_recomputes_search_text(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}})).json()["data"]["id"]
    sku_id = (await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "PCS", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "DN50"}]})).json()["data"]["id"]

    r = await client.put(f"/api/v1/skus/{sku_id}", headers=catalog_operator_headers, json={
        "name_i18n": {"zh": "阀", "en": "Ball Valve XYZ"},
        "spec_items": [{"key": "dn", "value": "DN80"}]})
    assert r.status_code == 200, r.text
    row = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert "Ball Valve XYZ" in row.search_text and "DN80" in row.search_text
    assert "DN50" not in row.search_text


@pytest.mark.asyncio
async def test_create_sku_rejects_duplicate_spec_key(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}})).json()["data"]["id"]
    r = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "PCS", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "1"}, {"key": "dn", "value": "2"}]})
    assert r.status_code == 400  # SpecContractError


@pytest.mark.asyncio
async def test_update_sku_rejects_name_without_zh(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}})).json()["data"]["id"]
    sku_id = (await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "PCS", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "DN50"}]})).json()["data"]["id"]
    # 改 SKU 名成无 zh → 422(zh 必填铁律,更新路径也守)
    r = await client.put(f"/api/v1/skus/{sku_id}", headers=catalog_operator_headers,
                         json={"name_i18n": {"en": "no zh"}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_handwritten_key_label_without_zh_rejected(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}})).json()["data"]["id"]
    # 手输新 key 但 label_i18n 无 zh → 400,不得污染模板(模板 label 也守 zh 必填)
    r = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "PCS", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "coating", "value": "x", "label_i18n": {"en": "Coating"}}]})
    assert r.status_code == 400
