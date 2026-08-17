"""payable.amount_outstanding 生成列范式:DB 恒等 + 应用层直写被拒。"""
import pytest
from sqlalchemy import select, update

from app.db.models.payable import Payable
from tests.inbound_helpers import setup_confirmed_po

pytestmark = pytest.mark.asyncio


async def _make_payable(client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 6}]})
    inb_id = cr.json()["data"]["order"]["id"]
    await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                      json={})
    return (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inb_id))).scalar_one()


async def test_amount_outstanding_db_identity(client, db_session, sales_headers, purchaser_headers):
    """amount_outstanding = original - adjusted - allocated,由 DB 生成。"""
    p = await _make_payable(client, db_session, sales_headers, purchaser_headers)
    assert float(p.amount_original) == 30.0
    assert float(p.amount_outstanding) == 30.0
    # 改 allocated,DB 重算 amount_outstanding。
    p.amount_allocated = 12
    await db_session.commit()
    await db_session.refresh(p)
    assert float(p.amount_outstanding) == 18.0


async def test_direct_write_to_amount_outstanding_rejected(
        client, db_session, sales_headers, purchaser_headers):
    """应用层直写生成列被 DB 拒(GENERATED ALWAYS 列不可写)。"""
    p = await _make_payable(client, db_session, sales_headers, purchaser_headers)
    with pytest.raises(Exception):
        await db_session.execute(
            update(Payable).where(Payable.id == p.id).values(amount_outstanding=999))
        await db_session.commit()
