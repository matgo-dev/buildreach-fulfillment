"""应收/应付详情端点(嵌活动核销记录)+ D10 未分配余额提示标志 + 红线门控。"""
import pytest

from tests.finance_helpers import make_open_payable, make_open_receivable

pytestmark = pytest.mark.asyncio


async def test_receivable_detail_embeds_active_allocations(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    reg = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "50.00",
        "received_at": "2026-07-21"})
    receivable_id = reg.json()["data"]["allocations"][0]["receivable_id"]

    d = await client.get(f"/api/v1/receivables/{receivable_id}", headers=finance_headers)
    assert d.status_code == 200, d.text
    body = d.json()["data"]
    assert body["status"] == "PAID" and float(body["balance"]) == 0.0
    assert len(body["allocations"]) == 1
    alloc = body["allocations"][0]
    assert alloc["receipt_no"].startswith("RC") and float(alloc["amount"]) == 50.0


async def test_receivable_list_flags_counterparty_unallocated(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """客户有未分配收款余额(预收)→ 其应收行 counterparty_has_unallocated=True(D10 提示)。"""
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    # 超收 80 → 冲满 50 + 30 预收
    await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "80.00",
        "received_at": "2026-07-21"})
    lst = await client.get("/api/v1/receivables", headers=finance_headers)
    row = next(it for it in lst.json()["data"]["items"] if it["outbound_order_id"] == ob_id)
    assert row["counterparty_has_unallocated"] is True


async def test_payable_detail_embeds_allocations_and_is_red_line_gated(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, supplier_id, pay_id, amount = await make_open_payable(
        client, db_session, sales_headers, purchaser_headers, po_price="5.00", received=10)
    await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "50.00", "paid_at": "2026-07-21"})

    d = await client.get(f"/api/v1/payables/{pay_id}", headers=finance_headers)
    assert d.status_code == 200, d.text
    assert d.json()["data"]["allocations"][0]["payment_no"].startswith("PM")
    # 🔴红线:LOGISTICS 无 payable:read → 详情 403
    assert (await client.get(f"/api/v1/payables/{pay_id}",
                             headers=logistics_headers)).status_code == 403


async def test_receivable_detail_red_line_gated(client, logistics_headers):
    """LOGISTICS 无 receivable:read → 应收详情 403(整端点红线门)。"""
    assert (await client.get("/api/v1/receivables/1",
                             headers=logistics_headers)).status_code == 403


async def test_receivable_hint_masked_for_sales_without_receipt_read(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """D10 提示位权限跟数据走:派生自收款域,SALES(持 receivable:read 无 receipt:read)
    恒 False——不经账层列表旁路感知收款单存在性;FINANCE 可见 True。"""
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "80.00",
        "received_at": "2026-07-21"})   # 冲满 50 + 30 预收
    fin = await client.get("/api/v1/receivables", headers=finance_headers)
    fin_row = next(it for it in fin.json()["data"]["items"] if it["outbound_order_id"] == ob_id)
    assert fin_row["counterparty_has_unallocated"] is True
    sal = await client.get("/api/v1/receivables", headers=sales_headers)
    sal_row = next(it for it in sal.json()["data"]["items"] if it["outbound_order_id"] == ob_id)
    assert sal_row["counterparty_has_unallocated"] is False


async def test_payable_detail_withholds_payment_domain_for_purchaser(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    """🔴红线:PURCHASER(持 payable:read 无 payment:read)看应付详情——账头(已冲/已付清)可见,
    但付款域核销记录整块不下发。与列表提示位同源门控:不该经账层详情旁路感知付款单存在性。"""
    ctx, supplier_id, pay_id, amount = await make_open_payable(
        client, db_session, sales_headers, purchaser_headers, po_price="5.00", received=10)
    await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "50.00", "paid_at": "2026-07-21"})
    # FINANCE:见付款单号
    fin = await client.get(f"/api/v1/payables/{pay_id}", headers=finance_headers)
    assert fin.json()["data"]["allocations"][0]["payment_no"].startswith("PM")
    # PURCHASER:账头照常(已冲 50 / 已付清),但 allocations 空 —— 付款单存在性不泄漏
    pur = await client.get(f"/api/v1/payables/{pay_id}", headers=purchaser_headers)
    assert pur.status_code == 200, pur.text
    body = pur.json()["data"]
    assert float(body["amount_allocated"]) == 50.0 and body["status"] == "PAID"
    assert body["allocations"] == []


async def test_receivable_detail_withholds_receipt_domain_for_sales(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """应收详情:SALES(持 receivable:read 无 receipt:read)——账头可见,收款域核销记录整块不下发。
    与列表提示位同源门控:不经账层详情旁路感知收款单存在性。"""
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    reg = await client.post("/api/v1/receipts", headers=finance_headers, json={
        "customer_id": ctx["customer"].id, "currency": "USD", "amount": "50.00",
        "received_at": "2026-07-21"})
    receivable_id = reg.json()["data"]["allocations"][0]["receivable_id"]
    fin = await client.get(f"/api/v1/receivables/{receivable_id}", headers=finance_headers)
    assert fin.json()["data"]["allocations"][0]["receipt_no"].startswith("RC")
    sal = await client.get(f"/api/v1/receivables/{receivable_id}", headers=sales_headers)
    assert sal.status_code == 200, sal.text
    body = sal.json()["data"]
    assert float(body["amount_allocated"]) == 50.0 and body["status"] == "PAID"
    assert body["allocations"] == []


async def test_payable_hint_masked_for_purchaser_without_payment_read(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    """🔴 D10 提示位(付侧):派生自红线付款域,PURCHASER(持 payable:read 无 payment:read)
    恒 False;FINANCE 可见 True。"""
    ctx, supplier_id, pay_id, amount = await make_open_payable(
        client, db_session, sales_headers, purchaser_headers, po_price="5.00", received=10)
    await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "80.00",
        "paid_at": "2026-07-21"})   # 冲满 50 + 30 预付
    fin = await client.get("/api/v1/payables", headers=finance_headers)
    fin_row = next(it for it in fin.json()["data"]["items"] if it["id"] == pay_id)
    assert fin_row["counterparty_has_unallocated"] is True
    pur = await client.get("/api/v1/payables", headers=purchaser_headers)
    pur_row = next(it for it in pur.json()["data"]["items"] if it["id"] == pay_id)
    assert pur_row["counterparty_has_unallocated"] is False
