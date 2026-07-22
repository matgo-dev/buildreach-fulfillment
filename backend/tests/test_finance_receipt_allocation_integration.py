"""收款单登记 + 自动核销(按账龄)集成测试。

自动核销:登记已认领收款(或认领后)同事务,按账龄 FIFO(due_at→created_at)逐张冲开口应收,
取满 min(收款未分配, 应收余额),多余留存为预收。核销引擎是 receipts/receivables
amount_allocated 唯一写入口。
"""
import pytest

from tests.finance_helpers import make_open_receivable
from tests.outbound_helpers import create_and_confirm_outbound, create_shipment, \
    setup_available_stock

pytestmark = pytest.mark.asyncio


async def test_auto_allocate_fills_oldest_receivable_first(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """同客户两张开口应收 → 收款按账龄 FIFO(created_at→id)先冲老单、再部分冲新单。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      sku_codes=("SKUFIN_AGE",), so_qty=10, unit_price="10.00",
                                      received=10)
    # 两张出库单须挂不同柜(同 (柜, SO) 唯一,41904);各产一张应收。
    ship1 = await create_shipment(client, logistics_headers)
    ship2 = await create_shipment(client, logistics_headers)
    so_line = ctx["so_lines"][0]["id"]
    ob1, c1 = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"], shipment_id=ship1["id"],
        lines=[{"sales_order_line_id": so_line, "qty": 4}])   # 应收1 = 40(先建)
    assert c1.status_code == 200, c1.text
    ob2, c2 = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"], shipment_id=ship2["id"],
        lines=[{"sales_order_line_id": so_line, "qty": 6}])   # 应收2 = 60(后建)
    assert c2.status_code == 200, c2.text

    # 收款 50 → 先冲满应收1(40),再部分冲应收2(10),应收2 余 50
    r = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "50.00",
        "received_at": "2026-07-21"})
    assert r.status_code == 200, r.text
    assert float(r.json()["data"]["receipt"]["amount_unallocated"]) == 0.0

    rv = (await client.get("/api/v1/receivables", headers=finance_headers)).json()["data"]["items"]
    bal = {it["outbound_order_id"]: float(it["balance"]) for it in rv}
    assert bal[ob1] == 0.0    # 老单冲满
    assert bal[ob2] == 50.0   # 新单部分冲(60-10)


async def test_register_receipt_full_auto_allocates_single_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """登记恰好覆盖一张应收的收款 → 自动核销 → 收款 FULLY_ALLOCATED、应收 PAID。"""
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="9.00", qty=6)  # 应收 = 54.00

    r = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "54.00",
        "received_at": "2026-07-21"})
    assert r.status_code == 200, r.text
    receipt = r.json()["data"]["receipt"]
    allocations = r.json()["data"]["allocations"]

    assert receipt["status"] == "FULLY_ALLOCATED"
    assert float(receipt["amount_allocated"]) == 54.0
    assert float(receipt["amount_unallocated"]) == 0.0
    assert receipt["receipt_no"].startswith("RC")
    # 一条 AUTO 核销记录冲这张应收
    assert len(allocations) == 1
    assert allocations[0]["alloc_type"] == "AUTO"
    assert float(allocations[0]["amount"]) == 54.0

    # 应收侧:balance 归零 → PAID
    rv = await client.get("/api/v1/receivables?status=PAID", headers=finance_headers)
    row = next(it for it in rv.json()["data"]["items"] if it["outbound_order_id"] == ob_id)
    assert float(row["balance"]) == 0.0


async def test_register_receipt_partial_leaves_receivable_partially_paid(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """收款少于应收 → 部分核销:收款 FULLY_ALLOCATED(全额用光)、应收 PARTIALLY_PAID、余额递减不清零。"""
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=10)  # 应收 = 100.00

    r = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "40.00",
        "received_at": "2026-07-21"})
    assert r.status_code == 200, r.text
    receipt = r.json()["data"]["receipt"]
    assert receipt["status"] == "FULLY_ALLOCATED"       # 收款 40 全部用于核销
    assert float(receipt["amount_unallocated"]) == 0.0

    rv = await client.get("/api/v1/receivables?status=PARTIALLY_PAID", headers=finance_headers)
    row = next(it for it in rv.json()["data"]["items"] if it["outbound_order_id"] == ob_id)
    assert float(row["balance"]) == 60.0


async def test_register_receipt_overpay_leaves_unallocated_prepayment(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """收款超应收 → 冲满应收后余额留存为预收(P0):收款 PARTIALLY_ALLOCATED、应收 PAID。"""
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 = 50.00

    r = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "80.00",
        "received_at": "2026-07-21"})
    assert r.status_code == 200, r.text
    receipt = r.json()["data"]["receipt"]
    assert receipt["status"] == "PARTIALLY_ALLOCATED"   # 50 核销 + 30 预收
    assert float(receipt["amount_allocated"]) == 50.0
    assert float(receipt["amount_unallocated"]) == 30.0


async def test_register_receipt_unclaimed_no_allocation(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """登记无客户收款(待认领)→ 不核销,状态 UNCLAIMED,全额未分配。"""
    r = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "currency": "USD", "amount": "100.00", "received_at": "2026-07-21"})
    assert r.status_code == 200, r.text
    receipt = r.json()["data"]["receipt"]
    assert receipt["status"] == "UNCLAIMED"
    assert receipt["customer_id"] is None
    assert float(receipt["amount_unallocated"]) == 100.0
    assert r.json()["data"]["allocations"] == []
