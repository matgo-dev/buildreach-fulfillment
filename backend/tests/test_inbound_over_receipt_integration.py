"""超收守卫 + quota 口径(锚点 1/8):在途计入、作废释放、exclude self 编辑重算。"""
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


async def test_cancel_releases_quota(client, db_session, sales_headers, purchaser_headers):
    """作废入库单释放 quota:作废后可重新开满。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    r1 = await _create(client, purchaser_headers, po_id, pl, 10)
    inb_id = r1.json()["data"]["order"]["id"]
    await client.post(f"/api/v1/inbound-orders/{inb_id}/cancel", headers=purchaser_headers)
    # 作废释放,可再开满。
    r2 = await _create(client, purchaser_headers, po_id, pl, 10)
    assert r2.status_code == 200, r2.text


async def test_edit_excludes_self(client, db_session, sales_headers, purchaser_headers):
    """编辑重算排除本单:在途 8,改成 10 应通过(不把自己旧 8 重复计入)。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    r1 = await _create(client, purchaser_headers, po_id, pl, 8)
    inb_id = r1.json()["data"]["order"]["id"]
    r2 = await client.put(f"/api/v1/inbound-orders/{inb_id}", headers=purchaser_headers, json={
        "lines": [{"purchase_order_line_id": pl, "qty": 10}],
        "expected_updated_at": r1.json()["data"]["order"]["updated_at"]})
    assert r2.status_code == 200, r2.text
    # 但改到 11 应被拒(超 PO 行量）。
    r3 = await client.put(f"/api/v1/inbound-orders/{inb_id}", headers=purchaser_headers, json={
        "lines": [{"purchase_order_line_id": pl, "qty": 11}],
        "expected_updated_at": r2.json()["data"]["order"]["updated_at"]})
    assert r3.status_code == 409 and r3.json()["code"] == 41703


async def test_edit_optimistic_lock_conflict(client, db_session, sales_headers, purchaser_headers):
    """乐观锁:陈旧 expected_updated_at → 41709(镜像 PO 41605)。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    pl = po_lines[0]["id"]
    r1 = await _create(client, purchaser_headers, po_id, pl, 5)
    inb_id = r1.json()["data"]["order"]["id"]
    r = await client.put(f"/api/v1/inbound-orders/{inb_id}", headers=purchaser_headers, json={
        "lines": [{"purchase_order_line_id": pl, "qty": 6}],
        "expected_updated_at": "2000-01-01T00:00:00"})
    assert r.status_code == 409 and r.json()["code"] == 41709


async def test_line_not_in_po_rejected(client, db_session, sales_headers, purchaser_headers):
    """入库行引用不属于该 PO 的 PO 行 → 41706。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    r = await _create(client, purchaser_headers, po_id, 999999, 1)
    assert r.status_code == 400 and r.json()["code"] == 41706
