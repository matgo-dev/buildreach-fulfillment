"""SKU 唯一 retrofit(契约 §0-11 / §1):报价重复 SKU 41412(service 前置)+ DB UNIQUE 兜底
+ 转单继承唯一性(SO 行来自报价转单)。业务公理:一 SKU 一价,无阶梯价/同 SKU 多价。
"""
import pytest

from tests.inventory_helpers import seed_inventory_catalog

pytestmark = pytest.mark.asyncio


async def test_quotation_create_duplicate_sku_rejected(client, db_session, sales_headers):
    cust, skus = await seed_inventory_catalog(db_session, sku_codes=("QDUP_A",))
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "summary": "重复SKU",
        "lines": [{"sku_id": skus[0].id, "unit_price": "5.00", "qty": 1},
                  {"sku_id": skus[0].id, "unit_price": "6.00", "qty": 2}]})
    assert r.status_code == 409 and r.json()["code"] == 41412


async def test_quotation_save_duplicate_sku_rejected(client, db_session, sales_headers):
    cust, skus = await seed_inventory_catalog(db_session, sku_codes=("QDUP_B",))
    cr = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "summary": "初版",
        "lines": [{"sku_id": skus[0].id, "unit_price": "5.00", "qty": 1}]})
    assert cr.status_code == 200, cr.text
    order = cr.json()["data"]
    r = await client.put(f"/api/v1/quotations/{order['id']}", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD",
        "expected_updated_at": order["updated_at"],
        "lines": [{"sku_id": skus[0].id, "unit_price": "5.00", "qty": 1},
                  {"sku_id": skus[0].id, "unit_price": "7.00", "qty": 3}]})
    assert r.status_code == 409 and r.json()["code"] == 41412


async def test_convert_inherits_uniqueness(client, db_session, sales_headers):
    """两个不同 SKU 报价 → 锁档 → 转单:SO 两行 SKU 互异(UNIQUE 继承)。"""
    cust, skus = await seed_inventory_catalog(db_session, sku_codes=("QU_A", "QU_B"))
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "summary": "两SKU",
        "lines": [{"sku_id": skus[0].id, "unit_price": "5.00", "qty": 1},
                  {"sku_id": skus[1].id, "unit_price": "6.00", "qty": 2}]})
    assert r.status_code == 200, r.text
    qid = r.json()["data"]["id"]
    await client.post(f"/api/v1/quotations/{qid}/lock", headers=sales_headers)
    conv = await client.post(f"/api/v1/quotations/{qid}/convert", headers=sales_headers)
    assert conv.status_code == 200, conv.text
    so_id = conv.json()["data"]["order"]["id"]
    detail = await client.get(f"/api/v1/sales-orders/{so_id}", headers=sales_headers)
    sku_ids = [ln["sku_id"] for ln in detail.json()["data"]["lines"]]
    assert len(sku_ids) == 2 and len(set(sku_ids)) == 2
