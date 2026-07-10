import pytest
from sqlalchemy import select

from app.db.models.category import Category


async def _seed_sku(client, headers, db_session, name_zh, spec):
    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    spu_id = (await client.post("/api/v1/spus", headers=headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}})).json()["data"]["id"]
    return (await client.post("/api/v1/skus", headers=headers, json={
        "spu_id": spu_id, "unit": "PCS", "name_i18n": {"zh": name_zh},
        "spec_items": spec})).json()["data"]


@pytest.mark.asyncio
async def test_search_hits_by_name_and_spec_and_code(
    client, superadmin_headers, catalog_operator_headers, db_session
):
    made = await _seed_sku(client, catalog_operator_headers, db_session,
                           "不锈钢法兰球阀 DN50", [{"key": "dn", "value": "DN50"}])
    for q in ["法兰球阀", "DN50", made["sku_code"]]:
        # 搜索是读:ADMIN 有 catalog:read,仍可用 superadmin_headers
        r = await client.get(f"/api/v1/skus?q={q}", headers=superadmin_headers)
        assert r.status_code == 200
        assert any(s["id"] == made["id"] for s in r.json()["data"]), q


@pytest.mark.asyncio
async def test_search_miss_returns_empty(
    client, superadmin_headers, catalog_operator_headers, db_session
):
    await _seed_sku(client, catalog_operator_headers, db_session,
                    "球阀", [{"key": "dn", "value": "DN50"}])
    r = await client.get("/api/v1/skus?q=完全不相关的词XYZ", headers=superadmin_headers)
    assert r.json()["data"] == []
