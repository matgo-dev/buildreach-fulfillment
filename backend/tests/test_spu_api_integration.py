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
async def test_spu_crud_flow(client, catalog_operator_headers, db_session):
    h = catalog_operator_headers
    await _seed_category(db_session, "10")
    r = await client.post("/api/v1/spus", headers=h,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"}})
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
    assert r.status_code == 200  # ADMIN 有 catalog:read


@pytest.mark.asyncio
async def test_spu_detail_cost_masked_for_read_only_role(client, superadmin_headers,
                                                          catalog_operator_headers, db_session):
    """详情内嵌 SKU 的 reference_price:CATALOG_MANAGE 可见,仅 CATALOG_READ 脱敏。"""
    await _seed_category(db_session, "10")
    r = await client.post("/api/v1/spus", headers=catalog_operator_headers,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"}})
    sid = r.json()["data"]["id"]
    r_sku = await client.post("/api/v1/skus", headers=catalog_operator_headers,
                              json={"spu_id": sid, "unit": "米", "reference_price": "12.50",
                                    "name_i18n": {"zh": "钢管A"}, "spec_items": []})
    assert r_sku.status_code in (200, 201), r_sku.text

    # CATALOG_MANAGE(operator)可见成本
    d_op = await client.get(f"/api/v1/spus/{sid}", headers=catalog_operator_headers)
    assert float(d_op.json()["data"]["skus"][0]["reference_price"]) == 12.50

    # 仅 CATALOG_READ(admin)看不到成本(脱敏为 None)
    d_admin = await client.get(f"/api/v1/spus/{sid}", headers=superadmin_headers)
    assert d_admin.json()["data"]["skus"][0]["reference_price"] is None


@pytest.mark.asyncio
async def test_spu_derived_availability(client, catalog_operator_headers, db_session):
    """派生可用性:ACTIVE SKU → 可用;SPU 下架 → 不可用但 SKU.status 不级联变化。"""
    h = catalog_operator_headers
    await _seed_category(db_session, "10")
    r = await client.post("/api/v1/spus", headers=h,
                          json={"category_code": "10", "name_i18n": {"zh": "钢管"}})
    sid = r.json()["data"]["id"]
    r_sku = await client.post("/api/v1/skus", headers=h,
                              json={"spu_id": sid, "unit": "米", "reference_price": "1.00",
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
