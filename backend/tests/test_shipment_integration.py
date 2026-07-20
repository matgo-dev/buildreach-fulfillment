"""发运单(=柜)骨架:建/改/取消 + 取消守卫(42001)+ 状态机(42002)+ 柜型校验。"""
import pytest

from tests.outbound_helpers import (
    create_outbound,
    create_shipment,
    setup_available_stock,
)

pytestmark = pytest.mark.asyncio


async def test_create_and_update_shipment(client, logistics_headers):
    ship = await create_shipment(client, logistics_headers, container_no="ABCU1234567",
                                 container_type="40HQ", seal_no="SEAL1")
    assert ship["status"] == "OPEN" and ship["no"].startswith("SH")
    r = await client.patch(f"/api/v1/shipments/{ship['id']}", headers=logistics_headers, json={
        "container_no": "XYZU7654321", "container_type": "20GP", "seal_no": "SEAL2"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["shipment"]["container_no"] == "XYZU7654321"
    assert r.json()["data"]["shipment"]["container_type"] == "20GP"


async def test_invalid_container_type_422(client, logistics_headers):
    r = await client.post("/api/v1/shipments", headers=logistics_headers,
                          json={"container_type": "99XX"})
    assert r.status_code == 422


async def test_cancel_empty_shipment(client, logistics_headers):
    ship = await create_shipment(client, logistics_headers)
    r = await client.post(f"/api/v1/shipments/{ship['id']}/cancel", headers=logistics_headers)
    assert r.status_code == 200
    assert r.json()["data"]["shipment"]["status"] == "CANCELLED"


async def test_cancel_blocked_with_active_outbound(client, db_session, sales_headers,
                                                   purchaser_headers, logistics_headers):
    """柜下有非 CANCELLED 出库单 → 取消拒 42001;取消柜内出库单后可取消柜。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    cr = await create_outbound(client, logistics_headers, sales_order_id=so_id,
                               shipment_id=ship["id"],
                               lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 3}])
    ob_id = cr.json()["data"]["order"]["id"]
    blocked = await client.post(f"/api/v1/shipments/{ship['id']}/cancel", headers=logistics_headers)
    assert blocked.status_code == 409 and blocked.json()["code"] == 42001
    # 取消出库单后柜可取消。
    await client.post(f"/api/v1/outbound-orders/{ob_id}/cancel", headers=logistics_headers)
    ok = await client.post(f"/api/v1/shipments/{ship['id']}/cancel", headers=logistics_headers)
    assert ok.status_code == 200, ok.text


async def test_cancelled_shipment_invalid_transition_and_edit(client, logistics_headers):
    """已取消柜再取消 → 42002(非法转移);改字段 → 42005(CANCELLED 可编辑集为空,diff 门禁)。"""
    ship = await create_shipment(client, logistics_headers)
    await client.post(f"/api/v1/shipments/{ship['id']}/cancel", headers=logistics_headers)
    again = await client.post(f"/api/v1/shipments/{ship['id']}/cancel", headers=logistics_headers)
    assert again.status_code == 409 and again.json()["code"] == 42002
    edit = await client.patch(f"/api/v1/shipments/{ship['id']}", headers=logistics_headers,
                              json={"container_no": "N"})
    assert edit.status_code == 400 and edit.json()["code"] == 42005


async def test_shipment_list_and_detail(client, db_session, sales_headers, purchaser_headers,
                                        logistics_headers):
    """列表投影柜内出库单数;详情含柜内出库单(组柜台)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    await create_outbound(client, logistics_headers, sales_order_id=so_id,
                          shipment_id=ship["id"],
                          lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 3}])
    lst = await client.get("/api/v1/shipments", headers=logistics_headers)
    assert lst.status_code == 200
    row = next(it for it in lst.json()["data"]["items"] if it["id"] == ship["id"])
    assert row["outbound_count"] == 1
    det = await client.get(f"/api/v1/shipments/{ship['id']}", headers=logistics_headers)
    assert det.json()["data"]["shipment"]["outbound_count"] == 1
    assert len(det.json()["data"]["outbound_orders"]) == 1
