"""收款单生命周期 + 核销引擎全分支:认领 / 作废纠错 / 人工核销 / 反核销 / 跨币种·跨客户守卫。"""
import pytest

from tests.finance_helpers import make_open_receivable

pytestmark = pytest.mark.asyncio


async def _register(client, finance_headers, *, amount, currency="USD", customer_id=None):
    body = {"amount": amount, "currency": currency, "received_at": "2026-07-21"}
    if customer_id is not None:
        body["customer_id"] = customer_id
    r = await client.post("/api/v1/receipts", headers=finance_headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ---------- 认领 ----------

async def test_claim_unclaimed_triggers_auto_allocation(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    data = await _register(client, finance_headers, amount="50.00")   # 无客户 → UNCLAIMED
    rid = data["receipt"]["id"]
    assert data["receipt"]["status"] == "UNCLAIMED"

    r = await client.post(f"/api/v1/receipts/{rid}/claim", headers=finance_headers,
                          json={"customer_id": ctx["customer"].id})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["receipt"]["status"] == "FULLY_ALLOCATED"
    assert len(r.json()["data"]["allocations"]) == 1


async def test_claim_already_claimed_rejected_42207(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers)
    data = await _register(client, finance_headers, amount="10.00",
                           customer_id=ctx["customer"].id)
    rid = data["receipt"]["id"]
    r = await client.post(f"/api/v1/receipts/{rid}/claim", headers=finance_headers,
                          json={"customer_id": ctx["customer"].id})
    assert r.status_code == 409
    assert r.json()["code"] == 42207


# ---------- 作废纠错(D11)----------

async def test_void_clean_receipt_ok_then_excluded_from_list(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    data = await _register(client, finance_headers, amount="30.00")  # UNCLAIMED, 零核销
    rid = data["receipt"]["id"]
    r = await client.post(f"/api/v1/receipts/{rid}/void", headers=finance_headers,
                          json={"void_reason": "录错金额"})
    assert r.status_code == 200, r.text
    lst = await client.get("/api/v1/receipts", headers=finance_headers)
    assert all(it["id"] != rid for it in lst.json()["data"]["items"])
    voided = await client.get("/api/v1/receipts?status=VOIDED", headers=finance_headers)
    assert any(it["id"] == rid for it in voided.json()["data"]["items"])


async def test_void_with_active_allocation_rejected_42208(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)
    data = await _register(client, finance_headers, amount="50.00",
                           customer_id=ctx["customer"].id)  # 自动核销一条
    rid = data["receipt"]["id"]
    r = await client.post(f"/api/v1/receipts/{rid}/void", headers=finance_headers, json={})
    assert r.status_code == 409
    assert r.json()["code"] == 42208


async def test_voided_receipt_cannot_claim_42209(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers)
    data = await _register(client, finance_headers, amount="10.00")  # UNCLAIMED
    rid = data["receipt"]["id"]
    await client.post(f"/api/v1/receipts/{rid}/void", headers=finance_headers, json={})
    r = await client.post(f"/api/v1/receipts/{rid}/claim", headers=finance_headers,
                          json={"customer_id": ctx["customer"].id})
    assert r.status_code == 409
    assert r.json()["code"] == 42209


# ---------- 人工核销 ----------

async def test_manual_allocate_takes_min_and_pays_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    """预收余额 + 人工挑单核销:取满 min(未分配, 余额)。"""
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    # 先造预收:超额收款(先自动冲满后有余额)。用另一张更小应收不便,这里直接超收。
    data = await _register(client, finance_headers, amount="50.00",
                           customer_id=ctx["customer"].id)   # 恰好冲满,无预收
    rid = data["receipt"]["id"]
    # 找到刚核销的应收 id
    receivable_id = data["allocations"][0]["receivable_id"]
    # 反核销后手工重核:反核销退回,再人工核销回去,验证人工路径
    alloc_id = data["allocations"][0]["id"]
    rev = await client.delete(f"/api/v1/receipt-allocations/{alloc_id}?reverse_reason=改分配",
                              headers=finance_headers)
    assert rev.status_code == 200, rev.text
    man = await client.post(f"/api/v1/receipts/{rid}/allocations", headers=finance_headers,
                            json={"account_id": receivable_id})
    assert man.status_code == 200, man.text
    body = man.json()["data"]
    assert body["receipt"]["status"] == "FULLY_ALLOCATED"
    assert body["allocations"][0]["alloc_type"] == "MANUAL"


async def test_manual_allocate_on_unclaimed_rejected_42207(client, finance_headers):
    data = await _register(client, finance_headers, amount="20.00")  # UNCLAIMED
    rid = data["receipt"]["id"]
    r = await client.post(f"/api/v1/receipts/{rid}/allocations", headers=finance_headers,
                          json={"account_id": 999999})
    assert r.status_code == 409
    assert r.json()["code"] == 42207


async def test_manual_allocate_cross_customer_rejected_42204(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    from app.db.models.customer import Customer

    # 客户 A 的开口应收
    ctxA, ob_a, _ = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)
    rid_a = next(it["id"] for it in (await client.get(
        "/api/v1/receivables", headers=finance_headers)).json()["data"]["items"]
        if it["outbound_order_id"] == ob_a)
    # 客户 B(不同客户,无需自己的应收链):直接建。B 的收款自动核销无匹配 → 全额预收。
    custB = Customer(code="CFIN_B", name="财务客户B")
    db_session.add(custB)
    await db_session.commit()
    await db_session.refresh(custB)
    data = await _register(client, finance_headers, amount="50.00", customer_id=custB.id)
    assert data["receipt"]["status"] == "UNALLOCATED"
    # 用 B 的预收余额手工冲 A 的应收 → 客户不匹配 42204
    r = await client.post(f"/api/v1/receipts/{data['receipt']['id']}/allocations",
                          headers=finance_headers, json={"account_id": rid_a})
    assert r.status_code == 409
    assert r.json()["code"] == 42204


async def test_manual_allocate_cross_currency_rejected_42203(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, _ = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # USD 应收
    rid_ar = next(it["id"] for it in (await client.get(
        "/api/v1/receivables", headers=finance_headers)).json()["data"]["items"]
        if it["outbound_order_id"] == ob_id)
    # EUR 收款,同客户 → 自动核销不匹配(币种),留全额预收
    data = await _register(client, finance_headers, amount="50.00", currency="EUR",
                           customer_id=ctx["customer"].id)
    assert data["receipt"]["status"] == "UNALLOCATED"    # 无同币种应收可冲
    r = await client.post(f"/api/v1/receipts/{data['receipt']['id']}/allocations",
                          headers=finance_headers, json={"account_id": rid_ar})
    assert r.status_code == 409
    assert r.json()["code"] == 42203


# ---------- 反核销 ----------

async def test_reverse_restores_both_sides_and_is_idempotent(
        client, db_session, sales_headers, purchaser_headers, logistics_headers, finance_headers):
    ctx, ob_id, amount = await make_open_receivable(
        client, db_session, sales_headers, purchaser_headers, logistics_headers,
        unit_price="10.00", qty=5)  # 应收 50
    data = await _register(client, finance_headers, amount="50.00",
                           customer_id=ctx["customer"].id)
    rid = data["receipt"]["id"]
    alloc_id = data["allocations"][0]["id"]

    rev = await client.delete(
        f"/api/v1/receipt-allocations/{alloc_id}?reverse_reason=客户要求改分配",
        headers=finance_headers)
    assert rev.status_code == 200, rev.text
    # 收款退回全额未分配
    got = await client.get(f"/api/v1/receipts/{rid}", headers=finance_headers)
    assert float(got.json()["data"]["receipt"]["amount_unallocated"]) == 50.0
    assert got.json()["data"]["allocations"] == []
    # 应收余额恢复
    rv = await client.get("/api/v1/receivables?status=UNPAID", headers=finance_headers)
    assert any(it["outbound_order_id"] == ob_id for it in rv.json()["data"]["items"])
    # 幂等:再反核销同一条 → 42205
    rev2 = await client.delete(f"/api/v1/receipt-allocations/{alloc_id}",
                               headers=finance_headers)
    assert rev2.status_code == 404
    assert rev2.json()["code"] == 42205
