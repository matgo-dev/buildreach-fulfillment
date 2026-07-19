"""审计痕迹(锚点 11):receive/unreceive 落 RECEIVE/UNRECEIVE(独立语义,不复用 CONFIRM/CANCEL)。"""
import pytest
from sqlalchemy import select

from app.db.models.audit_log import AuditLog
from tests.inbound_helpers import setup_confirmed_po

pytestmark = pytest.mark.asyncio


async def _logs_for(db_session, inbound_id):
    rows = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.resource_type == "inbound_order",
            AuditLog.resource_id == str(inbound_id)))).scalars().all()
    return list(rows)


async def _actions_for(db_session, inbound_id):
    return [r.action for r in await _logs_for(db_session, inbound_id)]


async def test_receive_unreceive_audit_trail(client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, unit_price="5.00")
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_lines[0]["id"], "qty": 4}]})
    inb_id = cr.json()["data"]["order"]["id"]
    rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive", headers=purchaser_headers,
                           json={})
    payable_id = rc.json()["data"]["payable"]["id"]
    await client.post(f"/api/v1/inbound-orders/{inb_id}/unreceive", headers=purchaser_headers,
                      json={})
    logs = await _logs_for(db_session, inb_id)
    actions = [r.action for r in logs]
    assert "CREATE" in actions
    assert "RECEIVE" in actions      # 收货独立语义,非 CONFIRM
    assert "UNRECEIVE" in actions    # 撤销独立语义,非 CANCEL
    # extra 可定位本次动作对应的 payable(撤销/重收后一单多条 payable,resource_id 不够)。
    by_action = {r.action: r for r in logs}
    assert by_action["RECEIVE"].extra == {"payable_id": payable_id}
    # unreceive 补穿仓校验后 extra 增校验摘要(契约 §2:原审计不变,extra 增 unreceive_check_ok)。
    assert by_action["UNRECEIVE"].extra == {"payable_id": payable_id, "unreceive_check_ok": True}
