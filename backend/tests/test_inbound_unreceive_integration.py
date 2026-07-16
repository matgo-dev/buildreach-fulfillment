"""撤销入库闭环(锚点 4):作废 payable 留痕 + 回在途 + quota 恢复 + allocated>0 拒 + 重收新账。"""
import pytest
from sqlalchemy import select

from app.db.models.payable import Payable
from tests.inbound_helpers import setup_confirmed_po

pytestmark = pytest.mark.asyncio


async def _create_and_receive(client, headers, po_id, po_line_id, qty):
    cr = await client.post("/api/v1/inbound-orders", headers=headers, json={
        "purchase_order_id": po_id, "lines": [{"purchase_order_line_id": po_line_id, "qty": qty}]})
    inb_id = cr.json()["data"]["order"]["id"]
    rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=headers, json={})
    assert rc.status_code == 200, rc.text
    return inb_id


async def test_unreceive_voids_payable_and_reopens(
        client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    pl = po_lines[0]["id"]
    inb_id = await _create_and_receive(client, purchaser_headers, po_id, pl, 4)

    ur = await client.post(f"/api/v1/inbound-orders/{inb_id}/unreceive", headers=purchaser_headers,
                           json={"void_reason": "误收"})
    assert ur.status_code == 200, ur.text
    assert ur.json()["data"]["order"]["status"] == "IN_TRANSIT"
    assert ur.json()["data"]["order"]["arrived_at"] is None   # 回在途即未到货,到货日随撤销清空
    assert "payable" not in ur.json()["data"]   # 在途无活动 payable 块

    # payable 行留痕:仍在库、voided_at/by/reason 有值、原金额仍在。
    rows = list((await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inb_id))).scalars().all())
    assert len(rows) == 1
    voided = rows[0]
    assert voided.voided_at is not None
    assert voided.voided_by is not None
    assert voided.void_reason == "误收"
    assert float(voided.amount_original) == 20.0   # 原金额不抹


async def test_unreceive_restores_quota_and_recount(
        client, db_session, sales_headers, purchaser_headers):
    """撤销后 quota 恢复,可重收 → 新建活动 payable(偏唯一不冲突,与作废行共存)。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    pl = po_lines[0]["id"]
    inb_id = await _create_and_receive(client, purchaser_headers, po_id, pl, 10)
    await client.post(f"/api/v1/inbound-orders/{inb_id}/unreceive", headers=purchaser_headers,
                      json={})
    # 重收:偏唯一只约束活动行,作废行不挡。
    rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                           json={})
    assert rc.status_code == 200, rc.text
    # 两张 payable(1 作废 + 1 活动);活动余额正确。
    rows = list((await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inb_id))).scalars().all())
    assert len(rows) == 2
    active = [r for r in rows if r.voided_at is None]
    assert len(active) == 1
    assert float(active[0].amount_original) == 50.0


async def test_unreceive_blocked_when_allocated(
        client, db_session, sales_headers, purchaser_headers):
    """payable 已核销(allocated>0)→ 撤销拒 41708(守卫先行;直改 mock allocated)。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    pl = po_lines[0]["id"]
    inb_id = await _create_and_receive(client, purchaser_headers, po_id, pl, 4)
    payable = (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inb_id))).scalar_one()
    payable.amount_allocated = 10
    await db_session.commit()

    ur = await client.post(f"/api/v1/inbound-orders/{inb_id}/unreceive", headers=purchaser_headers,
                           json={})
    assert ur.status_code == 409 and ur.json()["code"] == 41708
