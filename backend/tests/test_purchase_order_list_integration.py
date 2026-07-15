"""采购单列表筛选:来源销售单号(部分匹配)+ 供应商 + 状态。"""
import pytest

from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)


async def _po(client, H, so_id, sup_id, lid, qty=2):
    r = await client.post("/api/v1/purchase-orders", headers=H, json={
        "source_sales_order_id": so_id, "supplier_id": sup_id, "currency": "USD",
        "lines": [{"source_sales_order_line_id": lid, "qty": qty, "unit_price": 7}]})
    assert r.status_code == 200, r.text
    return r.json()["data"]["order"]


@pytest.mark.asyncio
async def test_filter_by_source_sales_order_no(client, purchaser_headers, sales_headers, db_session):
    """?source_sales_order_no 部分匹配来源 SO 单号,total 随之收敛(过滤在分页前)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    soA, la = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    soB, lb = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    poA = await _po(client, purchaser_headers, soA, sup["id"], la[0]["id"])
    await _po(client, purchaser_headers, soB, sup["id"], lb[0]["id"])

    # 取 SO-A 的单号,按它筛选采购单列表
    so_a_no = (await client.get(f"/api/v1/sales-orders/{soA}", headers=sales_headers)
               ).json()["data"]["order"]["no"]
    res = (await client.get(
        f"/api/v1/purchase-orders?source_sales_order_no={so_a_no}",
        headers=purchaser_headers)).json()["data"]
    assert res["total"] == 1
    assert res["items"][0]["id"] == poA["id"]
    assert res["items"][0]["source_sales_order_no"] == so_a_no


@pytest.mark.asyncio
async def test_filter_partial_match(client, purchaser_headers, sales_headers, db_session):
    """部分匹配:用 SO 号前缀('SO2026...')能命中(ilike 子串)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so, la = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    await _po(client, purchaser_headers, so, sup["id"], la[0]["id"])

    res = (await client.get(
        "/api/v1/purchase-orders?source_sales_order_no=SO2026",
        headers=purchaser_headers)).json()["data"]
    assert res["total"] >= 1
    assert all(it["source_sales_order_no"].startswith("SO2026") for it in res["items"])
