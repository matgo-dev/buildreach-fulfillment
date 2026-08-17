"""超收守卫 + quota 口径(锚点 1/8):在途计入;创建入库单后不可裸编辑/作废。"""
import pytest

from tests.inbound_helpers import setup_confirmed_po

pytestmark = pytest.mark.asyncio


async def _create(client, headers, po_id, po_line_id, qty):
    return await client.post("/api/v1/inbound-orders", headers=headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_line_id, "qty": qty}]})


async def test_over_receipt_across_two_asns(client, db_session, sales_headers, purchaser_headers):
    """两张 ASN 合计超 PO 行量 → 第二张 41703(守卫含在途)。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    r1 = await _create(client, purchaser_headers, po_id, pl, 7)
    assert r1.status_code == 200, r1.text
    # 第一张在途 7,第二张 4 → 合计 11 > 10(在途也计入守卫口径)。
    r2 = await _create(client, purchaser_headers, po_id, pl, 4)
    assert r2.status_code == 409
    assert r2.json()["code"] == 41703


async def test_in_transit_counts_toward_quota(client, db_session, sales_headers, purchaser_headers):
    """在途量计入守卫:开满即不可再开(即使未确认入库)。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    assert (await _create(client, purchaser_headers, po_id, pl, 10)).status_code == 200
    r = await _create(client, purchaser_headers, po_id, pl, 1)
    assert r.status_code == 409 and r.json()["code"] == 41703


async def test_cancel_blocked_after_payable_created_and_quota_retained(
        client, db_session, sales_headers, purchaser_headers):
    """创建入库单即生成应付,不可裸作废;额度仍被该在途入库占用。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    r1 = await _create(client, purchaser_headers, po_id, pl, 10)
    inb_id = r1.json()["data"]["order"]["id"]
    cx = await client.post(f"/api/v1/inbound-orders/{inb_id}/cancel", headers=purchaser_headers)
    assert cx.status_code == 409 and cx.json()["code"] == 41712
    # 作废被拒,额度不释放。
    r2 = await _create(client, purchaser_headers, po_id, pl, 10)
    assert r2.status_code == 409 and r2.json()["code"] == 41703


async def test_edit_blocked_after_payable_created(
        client, db_session, sales_headers, purchaser_headers):
    """创建入库单即生成应付,整单编辑不再作为裸回退/调整入口。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    r1 = await _create(client, purchaser_headers, po_id, pl, 8)
    inb_id = r1.json()["data"]["order"]["id"]
    r2 = await client.put(f"/api/v1/inbound-orders/{inb_id}", headers=purchaser_headers, json={
        "lines": [{"purchase_order_line_id": pl, "qty": 10}],
        "expected_updated_at": r1.json()["data"]["order"]["updated_at"]})
    assert r2.status_code == 409 and r2.json()["code"] == 41712


async def test_edit_boundary_takes_precedence_over_optimistic_lock(
        client, db_session, sales_headers, purchaser_headers):
    """创建入库单后编辑统一被财务边界拦截,不再进入乐观锁分支。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    r1 = await _create(client, purchaser_headers, po_id, pl, 5)
    inb_id = r1.json()["data"]["order"]["id"]
    r = await client.put(f"/api/v1/inbound-orders/{inb_id}", headers=purchaser_headers, json={
        "lines": [{"purchase_order_line_id": pl, "qty": 6}],
        "expected_updated_at": "2000-01-01T00:00:00"})
    assert r.status_code == 409 and r.json()["code"] == 41712


async def test_line_not_in_po_rejected(client, db_session, sales_headers, purchaser_headers):
    """入库行引用不属于该 PO 的 PO 行 → 41706。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    r = await _create(client, purchaser_headers, po_id, 999999, 1)
    assert r.status_code == 400 and r.json()["code"] == 41706


async def test_duplicate_po_line_rejected(client, db_session, sales_headers, purchaser_headers):
    """payload 同一 PO 行重复 → 41711(前置友好错,不打穿 DB UNIQUE 成 500);编辑同拒。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    r = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": pl, "qty": 3},
                  {"purchase_order_line_id": pl, "qty": 4}]})
    assert r.status_code == 400 and r.json()["code"] == 41711
    # 编辑路径先被履约财务边界拦截。
    r1 = await _create(client, purchaser_headers, po_id, pl, 5)
    inb_id = r1.json()["data"]["order"]["id"]
    r2 = await client.put(f"/api/v1/inbound-orders/{inb_id}", headers=purchaser_headers, json={
        "lines": [{"purchase_order_line_id": pl, "qty": 2},
                  {"purchase_order_line_id": pl, "qty": 3}],
        "expected_updated_at": r1.json()["data"]["order"]["updated_at"]})
    assert r2.status_code == 409 and r2.json()["code"] == 41712
