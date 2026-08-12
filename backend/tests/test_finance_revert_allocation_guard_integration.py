"""撤账 × 核销联动。

0811 后出库单 ISSUED 为正向终点,不再存在“反核销后撤销出库”路径。
入库侧仍保留应付核销挡撤销入库的基础回退能力。
"""
import pytest

from tests.finance_helpers import make_open_payable, make_open_receivable

pytestmark = pytest.mark.asyncio


async def test_outbound_revert_rejected_even_after_receipt_allocation_reversed(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    reg = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "50.00",
        "received_at": "2026-07-21"})
    alloc_id = reg.json()["data"]["allocations"][0]["id"]

    # 已出库 → 旧撤销入口统一拒绝,不再进入应收核销守卫。
    blocked = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert",
                                headers=logistics_headers, json={})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == 41901

    # 即使反核销退回,出库单仍不可回退原流程。
    await client.delete(f"/api/v1/receipt-allocations/{alloc_id}", headers=finance_headers)
    ok = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert",
                           headers=logistics_headers, json={})
    assert ok.status_code == 409 and ok.json()["code"] == 41901


async def test_payment_allocation_blocks_inbound_unreceive_then_reverse_unblocks(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx, supplier_id, pay_id, amount = await make_open_payable(
        client, db_session, sales_headers, purchaser_headers, po_price="5.00", received=10)
    inbound_id = ctx["inbound_order_id"]
    reg = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "50.00", "paid_at": "2026-07-21"})
    alloc_id = reg.json()["data"]["allocations"][0]["id"]

    # 应付已被核销 → 撤销入库被拦 41708
    blocked = await client.post(f"/api/v1/inbound-orders/{inbound_id}/unreceive",
                                headers=purchaser_headers, json={})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == 41708

    # 反核销退回 → 撤销入库放行
    await client.delete(f"/api/v1/payment-allocations/{alloc_id}", headers=finance_headers)
    ok = await client.post(f"/api/v1/inbound-orders/{inbound_id}/unreceive",
                           headers=purchaser_headers, json={})
    assert ok.status_code == 200, ok.text
