"""D2:撤账 × 核销联动。核销引擎建成后,41907(撤出库)/41708(撤入库)守卫才真正生效
(此前 amount_allocated 零写入口,守卫永不触发)。撤账路径已对活动账行 FOR UPDATE 重判,
与核销串行化(闭合 TOCTOU)。本测试证:有活动核销 → 撤账被拦;反核销后 → 撤账放行。

反例回归意义:若撤账仍用裸读(不锁)且守卫失效,「有核销仍能撤账」会让这些断言失败。
真并发交错(两连接)在 SAVEPOINT 单连接隔离夹具下不可实证,锁序正确性由代码结构 +
本功能门保证(撤账先提交→核销候选 WHERE voided_at IS NULL FOR UPDATE 靠 EPQ 排除;
核销先提交→撤账账行 FOR UPDATE 阻塞后读到 allocated>0 被拦)。
"""
import pytest

from tests.finance_helpers import make_open_payable, make_open_receivable

pytestmark = pytest.mark.asyncio


async def test_receipt_allocation_blocks_outbound_revert_then_reverse_unblocks(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    reg = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "50.00",
        "received_at": "2026-07-21"})
    alloc_id = reg.json()["data"]["allocations"][0]["id"]

    # 应收已被核销 → 撤销出库被拦 41907
    blocked = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert",
                                headers=logistics_headers, json={})
    assert blocked.status_code == 409
    assert blocked.json()["code"] == 41907

    # 反核销退回 → 撤销出库放行
    await client.delete(f"/api/v1/receipt-allocations/{alloc_id}", headers=finance_headers)
    ok = await client.post(f"/api/v1/outbound-orders/{ob_id}/revert",
                           headers=logistics_headers, json={})
    assert ok.status_code == 200, ok.text


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
