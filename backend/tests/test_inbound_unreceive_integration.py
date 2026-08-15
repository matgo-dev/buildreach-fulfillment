"""撤销入库闭环(锚点 4):只撤销库存事实;创建入库单产生的 payable 保持活动。"""
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
    assert "payable" in ur.json()["data"]   # 在途仍有创建入库单时生成的 payable

    # payable 行保持活动:撤销入库只影响库存状态,不作废财务事实。
    rows = list((await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inb_id))).scalars().all())
    assert len(rows) == 1
    active = rows[0]
    assert active.voided_at is None
    assert active.voided_by is None
    assert active.void_reason is None
    assert float(active.amount_original) == 20.0   # 原金额不抹


async def test_unreceive_restores_quota_and_recount(
        client, db_session, sales_headers, purchaser_headers):
    """撤销后可重收,且仍复用创建入库单时的同一张活动 payable。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    pl = po_lines[0]["id"]
    inb_id = await _create_and_receive(client, purchaser_headers, po_id, pl, 10)
    await client.post(f"/api/v1/inbound-orders/{inb_id}/unreceive", headers=purchaser_headers,
                      json={})
    # 重收:只改变库存状态,不新建 payable。
    rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                           json={})
    assert rc.status_code == 200, rc.text
    rows = list((await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inb_id))).scalars().all())
    assert len(rows) == 1
    active = [r for r in rows if r.voided_at is None]
    assert len(active) == 1
    assert float(active[0].amount_original) == 50.0


async def test_unreceive_not_blocked_when_payable_allocated_without_outbound(
        client, db_session, sales_headers, purchaser_headers):
    """payable 已核销也不挡撤销入库:该动作只撤销库存事实,不再作废应付。"""
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
    assert ur.status_code == 200, ur.text
    assert ur.json()["data"]["order"]["status"] == "IN_TRANSIT"
