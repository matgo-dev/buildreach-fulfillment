"""出库增量测试共用夹具助手(非 test_ 前缀,pytest 不收集)。

造「有可发库存的 CONFIRMED SO」的唯一路径 = 报价→锁档→转销售→采购→确认→入库→收货
(复用主流程)。出库/柜由 LOGISTICS 操作,采购/收货由 PURCHASER 操作。
"""
from tests.inbound_helpers import make_confirmed_po
from tests.inventory_helpers import (  # noqa: F401  (re-export 便利)
    make_confirmed_so,
    receive_inbound,
    seed_inventory_catalog,
)
from tests.purchase_helpers import create_supplier


async def setup_available_stock(client, db_session, sales_headers, purchaser_headers, *,
                                sku_codes=("SKUOB_A",), so_qty=10, unit_price="9.00",
                                po_price="5.00", received=None):
    """建到「有可发库存」:catalog(N SKU)→ CONFIRMED SO(每 SKU 一行 so_qty @ unit_price)
    → CONFIRMED PO(每行 so_qty @ po_price)→ 收货 received(默认=so_qty,None→不收)。
    返回 dict:customer / skus / sales_order_id / so_lines / purchase_order_id / po_lines。"""
    cust, skus = await seed_inventory_catalog(db_session, sku_codes=sku_codes)
    so_lines_in = [{"sku_id": s.id, "unit_price": unit_price, "qty": so_qty} for s in skus]
    so_id, so_lines = await make_confirmed_so(client, sales_headers, cust, so_lines_in)
    supplier = await create_supplier(client, purchaser_headers)
    po_line_payload = [{"source_sales_order_line_id": ln["id"], "qty": so_qty,
                        "unit_price": po_price} for ln in so_lines]
    po_id, po_lines = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=po_line_payload)
    recv = so_qty if received is None else received
    inbound_order_id = None
    if recv and recv > 0:
        inbound_order_id = await receive_inbound(
            client, purchaser_headers, purchase_order_id=po_id,
            lines=[{"purchase_order_line_id": pl["id"], "qty": recv} for pl in po_lines])
    return {
        "customer": cust, "skus": skus, "sales_order_id": so_id, "so_lines": so_lines,
        "purchase_order_id": po_id, "po_lines": po_lines,
        "inbound_order_id": inbound_order_id,
    }


async def create_shipment(client, logistics_headers, **fields):
    """建柜(OPEN),返回 shipment dict。"""
    r = await client.post("/api/v1/shipments", headers=logistics_headers, json=fields)
    assert r.status_code == 200, r.text
    return r.json()["data"]["shipment"]


async def create_outbound(client, logistics_headers, *, sales_order_id, shipment_id, lines):
    """建草稿出库单。lines: [{"sales_order_line_id":.., "qty":..}]。返回 httpx Response(调用方断言)。"""
    return await client.post("/api/v1/outbound-orders", headers=logistics_headers, json={
        "sales_order_id": sales_order_id, "shipment_id": shipment_id, "lines": lines})


async def create_and_confirm_outbound(client, logistics_headers, *, sales_order_id,
                                      shipment_id, lines):
    """建 + 确认装柜,返回 (outbound_id, confirm_response)。"""
    cr = await create_outbound(client, logistics_headers, sales_order_id=sales_order_id,
                               shipment_id=shipment_id, lines=lines)
    assert cr.status_code == 200, cr.text
    ob_id = cr.json()["data"]["order"]["id"]
    conf = await client.post(f"/api/v1/outbound-orders/{ob_id}/confirm", headers=logistics_headers)
    return ob_id, conf


async def make_loadable_shipment(client, db_session, sales_headers, purchaser_headers,
                                 logistics_headers, *, qty=5):
    """造一个「可装柜」的柜:有可发库存的 CONFIRMED SO + 一张 ISSUED 出库单进柜(OPEN)。
    返回 setup_available_stock 的 ctx + {shipment, outbound_id}。发运状态机测试的公共起点。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      so_qty=10, received=10)
    so_id, so_lines = ctx["sales_order_id"], ctx["so_lines"]
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": qty}])
    assert conf.status_code == 200, conf.text
    return {**ctx, "shipment": ship, "outbound_id": ob_id}
