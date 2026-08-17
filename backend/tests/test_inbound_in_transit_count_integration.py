"""采购单列表「在途 N」次要信号:仅 IN_TRANSIT 入库单计数(实收/已作废不算)。

与收货进度(实收口径)互补——回答「有几张货在路上未收」,不并入收货态。
"""
import pytest

from tests.inbound_helpers import setup_confirmed_po

pytestmark = pytest.mark.asyncio


async def _po_item(client, headers, po_id):
    r = await client.get("/api/v1/purchase-orders", headers=headers, params={"size": 100})
    assert r.status_code == 200, r.text
    items = [it for it in r.json()["data"]["items"] if it["id"] == po_id]
    assert items, f"PO {po_id} 不在列表"
    return items[0]


async def _new_inbound(client, headers, po_id, po_line_id, qty):
    r = await client.post("/api/v1/inbound-orders", headers=headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_line_id, "qty": qty}]})
    assert r.status_code == 200, r.text
    return r.json()["data"]["order"]["id"]


async def test_list_in_transit_count_counts_only_in_transit(
        client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pol = po_lines[0]["id"]

    # 无入库单:在途数 0,收货进度 未收货。
    it = await _po_item(client, purchaser_headers, po_id)
    assert it["in_transit_count"] == 0
    assert it["receipt_progress"] == "NOT_RECEIVED"

    # 建两张在途入库单(各 3,合计 6 ≤ 10)。
    inb_a = await _new_inbound(client, purchaser_headers, po_id, pol, 3)
    inb_b = await _new_inbound(client, purchaser_headers, po_id, pol, 3)
    it = await _po_item(client, purchaser_headers, po_id)
    assert it["in_transit_count"] == 2
    assert it["receipt_progress"] == "NOT_RECEIVED"  # 在途不算已收

    # 确认其一 → 在途降为 1,收货进度转部分收货(实收计入)。
    rc = await client.post(f"/api/v1/inbound-orders/{inb_a}/receive",
                           headers=purchaser_headers, json={})
    assert rc.status_code == 200, rc.text
    it = await _po_item(client, purchaser_headers, po_id)
    assert it["in_transit_count"] == 1
    assert it["receipt_progress"] == "PARTIALLY_RECEIVED"

    # 创建入库单后已产生应付,作废被边界拦截 → 在途仍保留。
    cx = await client.post(f"/api/v1/inbound-orders/{inb_b}/cancel",
                           headers=purchaser_headers, json={})
    assert cx.status_code == 409 and cx.json()["code"] == 41712
    it = await _po_item(client, purchaser_headers, po_id)
    assert it["in_transit_count"] == 1
    assert it["receipt_progress"] == "PARTIALLY_RECEIVED"
