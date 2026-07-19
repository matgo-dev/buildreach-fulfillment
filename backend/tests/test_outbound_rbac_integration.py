"""出库/柜/应收 RBAC 矩阵(契约 §3):LOGISTICS/SALES/PURCHASER 三角色端点可达性。

- LOGISTICS:出库/柜建改确认可达;应收 403(不持 receivable:read,应收=客户售价整表门控)。
- SALES:出库/柜/应收只读可达;写(建柜/建出库)403。
- PURCHASER:出库/柜/应收全 403(采购域与出库无交集)。
"""
import pytest

from tests.outbound_helpers import create_shipment, setup_available_stock

pytestmark = pytest.mark.asyncio


async def test_logistics_can_manage_but_not_receivables(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    # 建柜 + 建出库 + 确认可达。
    ship = await create_shipment(client, logistics_headers)
    cr = await client.post("/api/v1/outbound-orders", headers=logistics_headers, json={
        "sales_order_id": so_id, "shipment_id": ship["id"],
        "lines": [{"sales_order_line_id": so_lines[0]["id"], "qty": 3}]})
    assert cr.status_code == 200
    ob_id = cr.json()["data"]["order"]["id"]
    assert (await client.post(f"/api/v1/outbound-orders/{ob_id}/confirm",
                              headers=logistics_headers)).status_code == 200
    # 出库/柜列表可读;可发行可读。
    assert (await client.get("/api/v1/outbound-orders", headers=logistics_headers)).status_code == 200
    assert (await client.get("/api/v1/shipments", headers=logistics_headers)).status_code == 200
    assert (await client.get(f"/api/v1/sales-orders/{so_id}/outboundable-lines",
                             headers=logistics_headers)).status_code == 200
    # 应收 403(无 receivable:read)。
    assert (await client.get("/api/v1/receivables", headers=logistics_headers)).status_code == 403


async def test_sales_read_only(client, db_session, sales_headers, purchaser_headers,
                               logistics_headers):
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers)
    so_id = ctx["sales_order_id"]
    ship = await create_shipment(client, logistics_headers)
    # 读可达。
    assert (await client.get("/api/v1/outbound-orders", headers=sales_headers)).status_code == 200
    assert (await client.get("/api/v1/shipments", headers=sales_headers)).status_code == 200
    assert (await client.get("/api/v1/receivables", headers=sales_headers)).status_code == 200
    # 写 403:建柜、建出库、可发行(OUTBOUND_MANAGE)。
    assert (await client.post("/api/v1/shipments", headers=sales_headers,
                              json={})).status_code == 403
    assert (await client.post("/api/v1/outbound-orders", headers=sales_headers, json={
        "sales_order_id": so_id, "shipment_id": ship["id"],
        "lines": [{"sales_order_line_id": 1, "qty": 1}]})).status_code == 403
    assert (await client.get(f"/api/v1/sales-orders/{so_id}/outboundable-lines",
                             headers=sales_headers)).status_code == 403


async def test_purchaser_no_access(client, purchaser_headers):
    assert (await client.get("/api/v1/outbound-orders", headers=purchaser_headers)).status_code == 403
    assert (await client.get("/api/v1/shipments", headers=purchaser_headers)).status_code == 403
    assert (await client.get("/api/v1/receivables", headers=purchaser_headers)).status_code == 403
    assert (await client.post("/api/v1/shipments", headers=purchaser_headers,
                              json={})).status_code == 403
