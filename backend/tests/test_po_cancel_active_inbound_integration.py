"""PO 取消守卫(锚点 6):创建入库单后已产生应付,PO 不可裸取消。"""
import pytest

from tests.inbound_helpers import setup_confirmed_po

pytestmark = pytest.mark.asyncio


async def test_cancel_po_blocked_by_active_inbound(
        client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 3}]})
    inb_id = cr.json()["data"]["order"]["id"]
    # 在途入库单存在 → PO 取消被拒。
    r = await client.post(f"/api/v1/purchase-orders/{po_id}/cancel", headers=purchaser_headers)
    assert r.status_code == 409 and r.json()["code"] == 41609

    # 入库单创建即有应付,不可再通过裸作废释放 PO。
    cx = await client.post(f"/api/v1/inbound-orders/{inb_id}/cancel", headers=purchaser_headers)
    assert cx.status_code == 409 and cx.json()["code"] == 41712
    r2 = await client.post(f"/api/v1/purchase-orders/{po_id}/cancel", headers=purchaser_headers)
    assert r2.status_code == 409 and r2.json()["code"] == 41609


async def test_cancel_po_blocked_by_received_inbound(
        client, db_session, sales_headers, purchaser_headers):
    """已入库(RECEIVED)也算活动 → PO 取消被拒。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 3}]})
    inb_id = cr.json()["data"]["order"]["id"]
    await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers, json={})
    r = await client.post(f"/api/v1/purchase-orders/{po_id}/cancel", headers=purchaser_headers)
    assert r.status_code == 409 and r.json()["code"] == 41609
