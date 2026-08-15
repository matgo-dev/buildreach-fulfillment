"""创建入库单 → 应付款生成;确认入库只产生库存状态(锚点 2/3/9)。"""
import pytest
from sqlalchemy import select

from app.db.models.payable import Payable
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
    # 创建入库单即生成 payable;入库单据本身仍无金额字段。
    assert data["payable"]["amount_original"] > 0


async def test_create_generates_payable_amount_identity(
        client, db_session, sales_headers, purchaser_headers):
    """锚点3:payable.amount_original = Σ(行 qty × PO 行价 round2);balance 生成列 = original - allocated。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 3}]})
    assert cr.status_code == 200, cr.text
    data = cr.json()["data"]
    assert data["order"]["status"] == "IN_TRANSIT"
    assert data["order"]["arrived_at"] is None
    pay = data["payable"]
    assert pay["amount_original"] == 15.0        # 3 × 5.00
    assert pay["amount_allocated"] == 0.0
    assert pay["balance"] == 15.0                 # Computed: original - allocated
    assert pay["status"] == "UNPAID"
    assert pay["currency"] == "USD"


async def test_receive_does_not_create_second_payable(
        client, db_session, sales_headers, purchaser_headers):
    """确认入库只改库存状态,不重复生成 payable。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 3}]})
    inb_id = cr.json()["data"]["order"]["id"]
    payable_id = cr.json()["data"]["payable"]["id"]
    rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                           json={})
    assert rc.status_code == 200, rc.text
    data = rc.json()["data"]
    assert data["order"]["status"] == "RECEIVED"
    assert data["order"]["arrived_at"] is not None  # 默认当天
    assert data["payable"]["id"] == payable_id
    rows = list((await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inb_id))).scalars().all())
    assert len(rows) == 1


async def test_receive_is_idempotent(client, db_session, sales_headers, purchaser_headers):
    """锚点2:重复 receive → 友好错(非法转移),不产生第二张活动 payable。"""
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
    # 1.50 × 3.333 = 4.9995 → quantize(0.01) = 5.00。
    assert cr.json()["data"]["payable"]["amount_original"] == 5.0


async def test_amount_rounding_is_half_up(client, db_session, sales_headers, purchaser_headers):
    """钉死舍入模式:0.03 × 1.5 = 0.045 → HALF_UP = 0.05(half-even 会得 0.04,此值区分两种模式)。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="0.03")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 1.5}]})
    assert cr.json()["data"]["payable"]["amount_original"] == 0.05


async def test_zero_amount_payable_is_paid(client, db_session, sales_headers, purchaser_headers):
    """0 价 PO(unit_price=0 合法)→ payable 金额 0,余额 0 即无欠款,状态 = PAID 而非「未付」。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="0.00")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 3}]})
    pay = cr.json()["data"]["payable"]
    assert pay["amount_original"] == 0.0 and pay["balance"] == 0.0
    assert pay["status"] == "PAID"
