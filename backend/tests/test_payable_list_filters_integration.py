"""应付列表筛选:派生状态谓词(镜像 derive_payable_status)+ q 跨表模糊搜索。"""
import pytest

from tests.inbound_helpers import make_confirmed_po
from tests.purchase_helpers import create_supplier, make_confirmed_sales_order, seed_catalog_and_customer

pytestmark = pytest.mark.asyncio


async def _receive_all(client, headers, po_id, po_line_id, qty):
    r = await client.post("/api/v1/inbound-orders", headers=headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_line_id, "qty": qty}]})
    inb = r.json()["data"]["order"]
    rc = await client.post(f"/api/v1/inbound-orders/{inb['id']}/receive", headers=headers, json={})
    assert rc.status_code == 200, rc.text
    return inb


async def test_status_and_q_filters(client, db_session, sales_headers, purchaser_headers):
    """UNPAID(15元单)与 PAID(0元单)按 status 分开;q 命中 PO 号。"""
    # SO 行留 12 的额度:PO1 订 10(留 2 给 PO2),避免超采
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": "9.00", "qty": 12}])
    supplier = await create_supplier(client, purchaser_headers)

    # 单据1:3×5.00=15 → UNPAID
    po_id, po_lines = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": so_lines[0]["id"],
                                   "qty": 10, "unit_price": "5.00"}])
    await _receive_all(client, purchaser_headers, po_id, po_lines[0]["id"], 3)
    po_no = (await client.get(f"/api/v1/purchase-orders/{po_id}",
                              headers=purchaser_headers)).json()["data"]["order"]["no"]

    # 单据2(同 SO 另建 0 价 PO,余量 2):0 金额 → PAID(判序先 alloc>=orig)
    po2_id, po2_lines = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": so_lines[0]["id"],
                              "qty": 2, "unit_price": 0}])
    await _receive_all(client, purchaser_headers, po2_id, po2_lines[0]["id"], 2)

    async def fetch(**params):
        r = await client.get("/api/v1/payables", headers=purchaser_headers, params=params)
        assert r.status_code == 200, r.text
        return r.json()["data"]["items"]

    unpaid = await fetch(status="UNPAID")
    assert [float(i["amount_original"]) for i in unpaid] == [15.0]
    paid = await fetch(status="PAID")
    assert [float(i["amount_original"]) for i in paid] == [0.0]
    assert await fetch(status="PARTIALLY_PAID") == []
    # q 命中 PO 号(跨表 join 条件同时作用于 count 与行)
    hits = await fetch(q=po_no)
    assert len(hits) == 1 and hits[0]["purchase_order_no"] == po_no
    assert await fetch(q="不存在的关键词") == []
