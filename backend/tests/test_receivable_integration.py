"""应收款只读列表:生成/筛选/派生状态/作废行剔除 + 整表门控。"""
import pytest

from tests.outbound_helpers import create_and_confirm_outbound, create_shipment, \
    setup_available_stock

pytestmark = pytest.mark.asyncio


async def _confirm_one(client, db_session, sales_headers, purchaser_headers, logistics_headers,
                       *, unit_price="9.00", qty=6, sku_codes=("SKUOB_R",)):
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      sku_codes=sku_codes, so_qty=10, unit_price=unit_price,
                                      received=10)
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"], shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": qty}])
    assert conf.status_code == 200, conf.text
    return ctx, ob_id


async def test_receivable_appears_in_list(client, db_session, sales_headers, purchaser_headers,
                                          logistics_headers):
    ctx, ob_id = await _confirm_one(client, db_session, sales_headers, purchaser_headers,
                                    logistics_headers, unit_price="9.00", qty=6)
    r = await client.get("/api/v1/receivables", headers=sales_headers)
    assert r.status_code == 200
    row = next(it for it in r.json()["data"]["items"] if it["outbound_order_id"] == ob_id)
    assert row["amount_original"] == 54.0 and row["status"] == "UNPAID"
    assert row["customer_id"] == ctx["customer"].id
    assert "outbound_order_no" in row and "sales_order_no" in row


async def test_voided_receivable_excluded(client, db_session, sales_headers, purchaser_headers,
                                          logistics_headers):
    """撤销出库作废应收 → 列表(仅活动行)不再出现。"""
    ctx, ob_id = await _confirm_one(client, db_session, sales_headers, purchaser_headers,
                                    logistics_headers)
    await client.post(f"/api/v1/outbound-orders/{ob_id}/revert", headers=logistics_headers,
                      json={})
    r = await client.get("/api/v1/receivables", headers=sales_headers)
    assert all(it["outbound_order_id"] != ob_id for it in r.json()["data"]["items"])


async def test_status_filter(client, db_session, sales_headers, purchaser_headers,
                             logistics_headers):
    ctx, ob_id = await _confirm_one(client, db_session, sales_headers, purchaser_headers,
                                    logistics_headers)
    paid = await client.get("/api/v1/receivables?status=PAID", headers=sales_headers)
    assert all(it["outbound_order_id"] != ob_id for it in paid.json()["data"]["items"])
    unpaid = await client.get("/api/v1/receivables?status=UNPAID", headers=sales_headers)
    assert any(it["outbound_order_id"] == ob_id for it in unpaid.json()["data"]["items"])


async def test_receivable_gated_403(client, logistics_headers, purchaser_headers):
    """无 receivable:read(LOGISTICS/PURCHASER)→ 整端点 403。"""
    assert (await client.get("/api/v1/receivables", headers=logistics_headers)).status_code == 403
    assert (await client.get("/api/v1/receivables", headers=purchaser_headers)).status_code == 403
