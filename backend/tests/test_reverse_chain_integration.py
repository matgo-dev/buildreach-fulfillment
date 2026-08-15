"""0811 逆向边界联动:出库确认后原正向链路不可一路回退。

基础回退仍覆盖出库前的取消/撤销/反核销;一旦出库单 ISSUED,当前系统暂不支持
出库后线上冲正,不能再通过反核销、撤销出库、撤销入库一路退回销售单取消。
"""
import pytest

from tests.outbound_helpers import (
    create_and_confirm_outbound,
    create_shipment,
    setup_available_stock,
)

pytestmark = pytest.mark.asyncio


async def _payable_for_inbound(client, headers, inbound_id: int) -> dict:
    rows = (await client.get("/api/v1/payables", headers=headers)).json()["data"]["items"]
    return next(row for row in rows if row["inbound_order_id"] == inbound_id)


async def test_reverse_chain_stops_at_issued_outbound(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        sku_codes=("SKUREV_CHAIN",), so_qty=10, unit_price="9.00", po_price="5.00",
        received=10)
    so_id = ctx["sales_order_id"]
    po_id = ctx["purchase_order_id"]
    inbound_id = ctx["inbound_order_id"]
    so_line_id = ctx["so_lines"][0]["id"]

    ship = await create_shipment(client, logistics_headers)
    outbound_id, confirmed = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_line_id, "qty": 8}])
    assert confirmed.status_code == 200, confirmed.text

    receipt = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id,
        "currency": "USD",
        "amount": "72.00",
        "received_at": "2026-08-12",
    })
    assert receipt.status_code == 200, receipt.text
    receipt_alloc_id = receipt.json()["data"]["allocations"][0]["id"]

    payable = await _payable_for_inbound(client, purchaser_headers, inbound_id)
    payment = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": payable["supplier_id"],
        "currency": "USD",
        "amount": "50.00",
        "paid_at": "2026-08-12",
    })
    assert payment.status_code == 200, payment.text
    payment_alloc_id = payment.json()["data"]["allocations"][0]["id"]

    # 已出库后,旧撤销出库入口统一拒绝,不再取决于应收是否核销。
    blocked_outbound = await client.post(
        f"/api/v1/outbound-orders/{outbound_id}/revert",
        headers=logistics_headers, json={"void_reason": "联动测试"})
    assert blocked_outbound.status_code == 409
    assert blocked_outbound.json()["code"] == 41901

    # 已出库消费挡住撤销入库;应付是否核销不再决定库存事实撤销。
    blocked_inbound = await client.post(
        f"/api/v1/inbound-orders/{inbound_id}/unreceive",
        headers=purchaser_headers, json={"void_reason": "联动测试"})
    assert blocked_inbound.status_code == 409
    assert blocked_inbound.json()["code"] == 41710

    # 反核销收款后,仍不能撤销出库单。
    reverse_receipt = await client.delete(
        f"/api/v1/receipt-allocations/{receipt_alloc_id}?reverse_reason=联动测试",
        headers=finance_headers)
    assert reverse_receipt.status_code == 200, reverse_receipt.text
    reverted_outbound = await client.post(
        f"/api/v1/outbound-orders/{outbound_id}/revert",
        headers=logistics_headers, json={"void_reason": "联动测试"})
    assert reverted_outbound.status_code == 409
    assert reverted_outbound.json()["code"] == 41901

    # 反核销付款后,库存仍已被出库消费,撤销入库仍被 41710 挡住。
    reverse_payment = await client.delete(
        f"/api/v1/payment-allocations/{payment_alloc_id}?reverse_reason=联动测试",
        headers=finance_headers)
    assert reverse_payment.status_code == 200, reverse_payment.text
    unreceived = await client.post(
        f"/api/v1/inbound-orders/{inbound_id}/unreceive",
        headers=purchaser_headers, json={"void_reason": "联动测试"})
    assert unreceived.status_code == 409
    assert unreceived.json()["code"] == 41710
    cancelled_po = await client.post(f"/api/v1/purchase-orders/{po_id}/cancel",
                                     headers=purchaser_headers)
    assert cancelled_po.status_code == 409

    # 销售单仍被活动采购/出库链路挡住,不能取消原正向事实。
    cancelled_so = await client.post(f"/api/v1/sales-orders/{so_id}/cancel",
                                     headers=sales_headers,
                                     json={"reason": "联动测试"})
    assert cancelled_so.status_code == 409
