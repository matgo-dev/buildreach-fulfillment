"""付款单登记 + 自动核销 + 反核销(付侧镜像收侧,泛型引擎同一套逻辑)。🔴红线 RBAC。"""
import pytest

from tests.finance_helpers import make_open_payable

pytestmark = pytest.mark.asyncio


async def test_register_payment_auto_allocates_payable(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    """登记覆盖应付的付款 → 自动核销 → 付款 FULLY_ALLOCATED、应付 PAID。"""
    ctx, supplier_id, pay_id, amount = await make_open_payable(
        client, db_session, sales_headers, purchaser_headers, po_price="5.00", received=10)
    # 应付 = 10 × 5 = 50
    r = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "50.00",
        "paid_at": "2026-07-21"})
    assert r.status_code == 200, r.text
    payment = r.json()["data"]["payment"]
    assert payment["status"] == "FULLY_ALLOCATED"
    assert payment["payment_no"].startswith("PM")
    assert float(payment["amount_unallocated"]) == 0.0
    assert r.json()["data"]["allocations"][0]["alloc_type"] == "AUTO"

    pv = await client.get("/api/v1/payables?status=PAID", headers=finance_headers)
    assert any(it["id"] == pay_id for it in pv.json()["data"]["items"])


async def test_register_payment_overpay_leaves_prepayment(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    """付得多 → 冲满应付后余额留存为预付(P0 对称预收,不禁付得多)。"""
    ctx, supplier_id, pay_id, amount = await make_open_payable(
        client, db_session, sales_headers, purchaser_headers, po_price="5.00", received=10)
    r = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "80.00",
        "paid_at": "2026-07-21"})
    assert r.status_code == 200, r.text
    payment = r.json()["data"]["payment"]
    assert payment["status"] == "PARTIALLY_ALLOCATED"
    assert float(payment["amount_allocated"]) == 50.0
    assert float(payment["amount_unallocated"]) == 30.0


async def test_register_payment_no_open_payable_full_prepayment(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    """无开口应付先付(预付)→ 全额未分配留存,不禁。"""
    ctx, supplier_id, pay_id, amount = await make_open_payable(
        client, db_session, sales_headers, purchaser_headers, po_price="5.00", received=10)
    # 先付清应付
    await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "50.00", "paid_at": "2026-07-21"})
    # 再付一笔(无开口应付)→ 全额预付
    r = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "20.00", "paid_at": "2026-07-21"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["payment"]["status"] == "UNALLOCATED"
    assert float(r.json()["data"]["payment"]["amount_unallocated"]) == 20.0


async def test_reverse_payment_allocation_restores_both_sides(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx, supplier_id, pay_id, amount = await make_open_payable(
        client, db_session, sales_headers, purchaser_headers, po_price="5.00", received=10)
    r = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": supplier_id, "currency": "USD", "amount": "50.00", "paid_at": "2026-07-21"})
    data = r.json()["data"]
    pid, alloc_id = data["payment"]["id"], data["allocations"][0]["id"]

    rev = await client.delete(f"/api/v1/payment-allocations/{alloc_id}", headers=finance_headers)
    assert rev.status_code == 200, rev.text
    got = await client.get(f"/api/v1/payments/{pid}", headers=finance_headers)
    assert float(got.json()["data"]["payment"]["amount_unallocated"]) == 50.0
    pv = await client.get("/api/v1/payables?status=UNPAID", headers=finance_headers)
    assert any(it["id"] == pay_id for it in pv.json()["data"]["items"])


# ---------- 🔴红线 RBAC ----------

async def test_payments_gated_403_for_non_payment_roles(
        client, sales_headers, logistics_headers):
    """无 payment:read(SALES/LOGISTICS)→ 付款单整端点 403(不下发供应商+采购付款真值)。"""
    assert (await client.get("/api/v1/payments", headers=sales_headers)).status_code == 403
    assert (await client.get("/api/v1/payments", headers=logistics_headers)).status_code == 403


async def test_payment_manage_gated_403(client, sales_headers):
    r = await client.post("/api/v1/payments", headers=sales_headers, json={
        "supplier_id": 1, "currency": "USD", "amount": "10.00", "paid_at": "2026-07-21"})
    assert r.status_code == 403


async def test_purchaser_can_read_payables_but_not_payments(client, purchaser_headers):
    """PURCHASER 持 payable:read(看账层欠款)但不持 payment:read(不看付款执行明细)。"""
    assert (await client.get("/api/v1/payables", headers=purchaser_headers)).status_code == 200
    assert (await client.get("/api/v1/payments", headers=purchaser_headers)).status_code == 403


async def test_register_payment_unknown_supplier_404(client, finance_headers):
    """FK 前置判:不存在的 supplier_id → 41501(404),不裸撞 FK IntegrityError 500。"""
    r = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": 999999, "currency": "USD", "amount": "10.00", "paid_at": "2026-07-21"})
    assert r.status_code == 404, r.text
    assert r.json()["code"] == 41501


async def test_register_payment_amount_validation_422(client, finance_headers):
    """脏金额在 schema 层 422 拒(镜像收侧)。"""
    for bad in ("abc", "-5", "0", "10.005"):
        r = await client.post("/api/v1/payments", headers=finance_headers, json={
            "supplier_id": 1, "currency": "USD", "amount": bad, "paid_at": "2026-07-21"})
        assert r.status_code == 422, f"amount={bad}: {r.text}"
