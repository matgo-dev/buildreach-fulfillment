"""unreceive 穿仓守卫补全(库存契约 §2,收紧型写入口第二个):货已被出库消费,
撤销入库将使 (SO,SKU) 可发穿仓(available<0)→ 拒 41710;先撤销出库后可撤销入库。

出库×unreceive 并发穿仓拒绝(库存契约预订用例,顺序化验证):锁序 SO头→入库头,
锁内翻转后派生校验 available≥0。
"""
import pytest

from tests.outbound_helpers import create_and_confirm_outbound, create_shipment, \
    setup_available_stock

pytestmark = pytest.mark.asyncio


async def test_unreceive_blocked_when_stock_outbound(client, db_session, sales_headers,
                                                     purchaser_headers, logistics_headers):
    """收货 10,出库 8(ISSUED)。撤销入库将使 available = 0−8 < 0 → 41710。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=10)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    inb_id = ctx["inbound_order_id"]
    ship = await create_shipment(client, logistics_headers)
    _, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 8}])
    assert conf.status_code == 200

    ur = await client.post(f"/api/v1/inbound-orders/{inb_id}/unreceive",
                           headers=purchaser_headers, json={"void_reason": "误收"})
    assert ur.status_code == 409 and ur.json()["code"] == 41710
    # 入库单仍 RECEIVED(事务回滚,状态翻转撤销)。
    d = await client.get(f"/api/v1/inbound-orders/{inb_id}", headers=purchaser_headers)
    assert d.json()["data"]["order"]["status"] == "RECEIVED"


async def test_unreceive_ok_after_revert_outbound(client, db_session, sales_headers,
                                                  purchaser_headers, logistics_headers):
    """撤销出库释放库存后,撤销入库不再穿仓 → 通过。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=10)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    inb_id = ctx["inbound_order_id"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 8}])
    assert conf.status_code == 200
    # 先撤销出库(available 回 10)。
    await client.post(f"/api/v1/outbound-orders/{ob_id}/revert", headers=logistics_headers,
                      json={})
    ur = await client.post(f"/api/v1/inbound-orders/{inb_id}/unreceive",
                           headers=purchaser_headers, json={})
    assert ur.status_code == 200, ur.text
    assert ur.json()["data"]["order"]["status"] == "IN_TRANSIT"


async def test_unreceive_ok_when_no_outbound(client, db_session, sales_headers,
                                             purchaser_headers, logistics_headers):
    """无出库消费:撤销入库照常通过(守卫不误伤)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=10)
    inb_id = ctx["inbound_order_id"]
    ur = await client.post(f"/api/v1/inbound-orders/{inb_id}/unreceive",
                           headers=purchaser_headers, json={})
    assert ur.status_code == 200, ur.text
