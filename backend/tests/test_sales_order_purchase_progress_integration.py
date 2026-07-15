"""SO 侧采购进度扩展(不改表,派生):列表进度徽标 + 筛选、详情 covered_qty + 关联PO区门控。

进度=轴2 机器派生(方案B),共用 compute_covered_qty 单一口径。related_po 区仅 purchase:read 下发
(供应商身份红线由端点级门控,SALES 拿不到)。
"""
import pytest

from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)


async def _po(client, H, so_id, sup_id, so_line_id, qty):
    return await client.post("/api/v1/purchase-orders", headers=H, json={
        "source_sales_order_id": so_id, "supplier_id": sup_id, "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_line_id, "qty": qty, "unit_price": 7}]})


@pytest.mark.asyncio
async def test_detail_progress_not_ordered(client, purchaser_headers, sales_headers, db_session):
    """未下单:详情 purchase_progress=NOT_ORDERED,每行 covered_qty=0。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    d = (await client.get(f"/api/v1/sales-orders/{so_id}", headers=purchaser_headers)).json()["data"]
    assert d["order"]["purchase_progress"] == "NOT_ORDERED"
    assert float(d["lines"][0]["covered_qty"]) == 0


@pytest.mark.asyncio
async def test_detail_progress_partial_then_full(client, purchaser_headers, sales_headers, db_session):
    """部分下单→PARTIALLY;补齐→FULLY。covered_qty 反映累计(含草稿)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    lid = so_lines[0]["id"]

    assert (await _po(client, purchaser_headers, so_id, sup["id"], lid, 2)).status_code == 200
    d = (await client.get(f"/api/v1/sales-orders/{so_id}", headers=purchaser_headers)).json()["data"]
    assert d["order"]["purchase_progress"] == "PARTIALLY_ORDERED"
    assert float(d["lines"][0]["covered_qty"]) == 2

    assert (await _po(client, purchaser_headers, so_id, sup["id"], lid, 3)).status_code == 200
    d = (await client.get(f"/api/v1/sales-orders/{so_id}", headers=purchaser_headers)).json()["data"]
    assert d["order"]["purchase_progress"] == "FULLY_ORDERED"
    assert float(d["lines"][0]["covered_qty"]) == 5


@pytest.mark.asyncio
async def test_cancelled_po_releases_coverage(client, purchaser_headers, sales_headers, db_session):
    """取消 PO 释放额度:进度回落 NOT_ORDERED,covered_qty 归 0(排除 CANCELLED)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    r = await _po(client, purchaser_headers, so_id, sup["id"], so_lines[0]["id"], 5)
    po_id = r.json()["data"]["order"]["id"]
    await client.post(f"/api/v1/purchase-orders/{po_id}/cancel", headers=purchaser_headers)

    d = (await client.get(f"/api/v1/sales-orders/{so_id}", headers=purchaser_headers)).json()["data"]
    assert d["order"]["purchase_progress"] == "NOT_ORDERED"
    assert float(d["lines"][0]["covered_qty"]) == 0


@pytest.mark.asyncio
async def test_related_po_visible_to_purchaser_incl_cancelled(client, purchaser_headers,
                                                              sales_headers, db_session):
    """purchase:read 者:详情带 related_purchase_orders(含 CANCELLED 并标状态,可追溯);
    有 read_cost 见真实金额。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    r = await _po(client, purchaser_headers, so_id, sup["id"], so_lines[0]["id"], 2)
    po = r.json()["data"]["order"]
    await client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=purchaser_headers)

    d = (await client.get(f"/api/v1/sales-orders/{so_id}", headers=purchaser_headers)).json()["data"]
    related = d["order"]["related_purchase_orders"]
    assert len(related) == 1
    assert related[0]["no"] == po["no"]
    assert related[0]["status"] == "CANCELLED"
    assert related[0]["supplier_display"] == "供应商甲"
    assert float(related[0]["total_amount"]) == 14  # 7×2,采购员有 read_cost


@pytest.mark.asyncio
async def test_sales_role_gets_no_related_po_block(client, sales_headers, purchaser_headers,
                                                   db_session):
    """SALES(无 purchase:read):详情结构上不含 related_purchase_orders(端点级门控,供应商身份红线)。
    但仍见进度徽标 + covered_qty(数量非红线)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    await _po(client, purchaser_headers, so_id, sup["id"], so_lines[0]["id"], 2)

    d = (await client.get(f"/api/v1/sales-orders/{so_id}", headers=sales_headers)).json()["data"]
    assert "related_purchase_orders" not in d["order"]
    assert d["order"]["purchase_progress"] == "PARTIALLY_ORDERED"
    assert float(d["lines"][0]["covered_qty"]) == 2


@pytest.mark.asyncio
async def test_list_progress_badge_and_filter(client, purchaser_headers, sales_headers, db_session):
    """列表:每项带 purchase_progress;?purchase_progress 筛选 total 正确(过滤在分页前)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    # SO1 未下单,SO2 已下单
    so1, _ = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    so2, so2_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    await _po(client, purchaser_headers, so2, sup["id"], so2_lines[0]["id"], 5)

    all_lst = (await client.get("/api/v1/sales-orders?status=CONFIRMED",
                                headers=purchaser_headers)).json()["data"]
    prog = {it["id"]: it["purchase_progress"] for it in all_lst["items"]}
    assert prog[so1] == "NOT_ORDERED" and prog[so2] == "FULLY_ORDERED"

    only_unordered = (await client.get(
        "/api/v1/sales-orders?status=CONFIRMED&purchase_progress=NOT_ORDERED",
        headers=purchaser_headers)).json()["data"]
    ids = {it["id"] for it in only_unordered["items"]}
    assert so1 in ids and so2 not in ids
    assert only_unordered["total"] == len([1 for p in prog.values() if p == "NOT_ORDERED"])
