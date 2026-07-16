"""入库确认 → 应付款生成:金额恒等 + Computed 余额 + 确认幂等(锚点 2/3/9)。"""
import pytest

from tests.inbound_helpers import setup_confirmed_po

pytestmark = pytest.mark.asyncio


async def test_create_inbound_is_in_transit(client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(client, db_session, sales_headers, purchaser_headers)
    r = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id, "carrier_name": "专线A", "tracking_no": "TRK001",
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 4}]})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["order"]["status"] == "IN_TRANSIT"
    assert data["order"]["no"].startswith("IN")
    # 入库单据零成本列:响应无金额字段。
    assert "total_amount" not in data["order"]
    assert all("unit_price" not in ln and "line_total" not in ln for ln in data["lines"])
    # 在途尚无 payable 块。
    assert "payable" not in data


async def test_receive_generates_payable_amount_identity(
        client, db_session, sales_headers, purchaser_headers):
    """锚点3:payable.amount_original = Σ(行 qty × PO 行价 round2);balance 生成列 = original - allocated。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 3}]})
    inb_id = cr.json()["data"]["order"]["id"]
    rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                           json={})
    assert rc.status_code == 200, rc.text
    data = rc.json()["data"]
    assert data["order"]["status"] == "RECEIVED"
    assert data["order"]["arrived_at"] is not None  # 默认当天
    pay = data["payable"]
    assert pay["amount_original"] == 15.0        # 3 × 5.00
    assert pay["amount_allocated"] == 0.0
    assert pay["balance"] == 15.0                 # Computed: original - allocated
    assert pay["status"] == "UNPAID"
    assert pay["currency"] == "USD"


async def test_receive_is_idempotent(client, db_session, sales_headers, purchaser_headers):
    """锚点2:重复 receive → 不产生第二张活动 payable,友好错(非法转移)。"""
    po_id, po_lines = await setup_confirmed_po(client, db_session, sales_headers, purchaser_headers)
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 2}]})
    inb_id = cr.json()["data"]["order"]["id"]
    r1 = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                           json={})
    assert r1.status_code == 200, r1.text
    r2 = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                           json={})
    assert r2.status_code == 409
    assert r2.json()["code"] == 41704   # 非法转移 RECEIVED→RECEIVED


async def test_amount_quantize_3dp_qty(client, db_session, sales_headers, purchaser_headers):
    """行金额逐行 quantize 2dp:qty(3dp) × 价(2dp) 产生 5dp 乘积,quantize 到 2dp。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="1.50")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 3.333}]})
    inb_id = cr.json()["data"]["order"]["id"]
    rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                           json={})
    # 1.50 × 3.333 = 4.9995 → quantize(0.01) = 5.00。
    assert rc.json()["data"]["payable"]["amount_original"] == 5.0
