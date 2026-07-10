import pytest
from decimal import Decimal
from sqlalchemy import select

from app.db.models.quotation import QuotationLine


async def _prep(client, headers, db_session, cust_lang=None):
    from app.db.models.category import Category
    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    cust = (await client.post("/api/v1/customers", headers=headers,
            json={"name_i18n": {"zh": "客户A"}, "preferred_language": cust_lang})).json()["data"]
    spu_id = (await client.post("/api/v1/spus", headers=headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}})).json()["data"]["id"]
    sku = (await client.post("/api/v1/skus", headers=headers, json={
        "spu_id": spu_id, "unit": "PCS", "name_i18n": {"zh": "不锈钢球阀 DN50"},
        "spec_items": [{"key": "dn", "value": "DN50"}]})).json()["data"]
    return cust, sku


@pytest.mark.asyncio
async def test_draft_language_defaults_from_customer_pref(client, superadmin_headers, db_session):
    cust, _ = await _prep(client, superadmin_headers, db_session, cust_lang="sw-TZ")
    r = await client.post("/api/v1/quotations", headers=superadmin_headers,
                          json={"customer_id": cust["id"], "currency": "USD"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["language"] == "sw"   # sw-TZ → sw
    assert r.json()["data"]["no"].startswith("Q")


@pytest.mark.asyncio
async def test_add_line_snapshots_and_computes_total(client, superadmin_headers, db_session):
    cust, sku = await _prep(client, superadmin_headers, db_session)  # 无 pref → language zh
    order = (await client.post("/api/v1/quotations", headers=superadmin_headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    r = await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
                          json={"sku_id": sku["id"], "unit_price": 128.0, "qty": 3})
    assert r.status_code == 200, r.text
    line = r.json()["data"]
    assert line["name_snapshot"] == "不锈钢球阀 DN50"
    assert "DN50" in line["spec_text_snapshot"]
    assert line["unit_snapshot"] == "PCS"
    assert Decimal(str(line["line_total"])) == Decimal("384.00")  # 128*3


@pytest.mark.asyncio
async def test_snapshot_frozen_after_main_data_change(client, superadmin_headers, db_session):
    cust, sku = await _prep(client, superadmin_headers, db_session)
    order = (await client.post("/api/v1/quotations", headers=superadmin_headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    line = (await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
            json={"sku_id": sku["id"], "unit_price": 100.0, "qty": 1})).json()["data"]
    # 改 SKU 主数据
    await client.put(f"/api/v1/skus/{sku['id']}", headers=superadmin_headers,
                     json={"name_i18n": {"zh": "改名后的阀"}})
    # 报价行快照不变
    row = (await db_session.execute(
        select(QuotationLine).where(QuotationLine.id == line["id"]))).scalar_one()
    assert row.name_snapshot == "不锈钢球阀 DN50"


@pytest.mark.asyncio
async def test_line_snapshot_editable_override(client, superadmin_headers, db_session):
    cust, sku = await _prep(client, superadmin_headers, db_session)
    order = (await client.post("/api/v1/quotations", headers=superadmin_headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    r = await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
                          json={"sku_id": sku["id"], "unit_price": 100.0, "qty": 1,
                                "name_snapshot": "线下定稿名"})
    assert r.json()["data"]["name_snapshot"] == "线下定稿名"
