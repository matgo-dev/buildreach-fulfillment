"""入库增量测试共用夹具助手(非 test_ 前缀,pytest 不收集)。

建 CONFIRMED PO 的唯一路径 = 报价→锁档→转销售→建采购单→确认(复用主流程),供入库测试取 po_line。
"""
from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)


async def make_confirmed_po(client, purchaser_headers, *, source_sales_order_id, so_lines,
                            supplier, currency="USD", lines):
    """基于 SO 行建 PO 并确认。lines: [{"source_sales_order_line_id":.., "qty":.., "unit_price":..}]。
    返回 (po_id, [po_line dict...])。po_line dict 的 'id' 即入库要用的 purchase_order_line_id。"""
    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": source_sales_order_id, "supplier_id": supplier["id"],
        "currency": currency, "lines": lines})
    assert r.status_code == 200, r.text
    po = r.json()["data"]["order"]
    conf = await client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=purchaser_headers)
    assert conf.status_code == 200, conf.text
    detail = (await client.get(f"/api/v1/purchase-orders/{po['id']}",
                               headers=purchaser_headers)).json()["data"]
    return po["id"], detail["lines"]


async def setup_confirmed_po(client, db_session, sales_headers, purchaser_headers,
                             *, so_qty=10, unit_price="5.00", reference_price=None):
    """一站式:catalog+客户 → CONFIRMED SO(1 行 so_qty)→ CONFIRMED PO(1 行 so_qty @ unit_price)。
    返回 (po_id, po_lines)。po_lines[0]['id'] = 可入库的 PO 行 id。"""
    cust, sku = await seed_catalog_and_customer(db_session, reference_price=reference_price)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": "9.00", "qty": so_qty}])
    supplier = await create_supplier(client, purchaser_headers)
    po_id, po_lines = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": so_lines[0]["id"],
                                   "qty": so_qty, "unit_price": unit_price}])
    return po_id, po_lines
