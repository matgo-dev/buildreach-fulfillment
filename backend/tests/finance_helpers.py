"""财务增量测试 helper:造一张开口应收 / 应付,供收付款核销测试复用。"""
from __future__ import annotations

from tests.outbound_helpers import (
    create_and_confirm_outbound,
    create_shipment,
    setup_available_stock,
)


async def make_open_receivable(client, db_session, sales_headers, purchaser_headers,
                               logistics_headers, *, unit_price="9.00", qty=6,
                               sku_codes=("SKUFIN_R",)):
    """造一张 UNPAID 应收:建可发库存 → 建柜 → 确认出库。
    返回 (ctx, outbound_order_id, receivable_amount)。receivable.currency = USD(SO 币种)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      sku_codes=sku_codes, so_qty=10, unit_price=unit_price,
                                      received=10)
    ship = await create_shipment(client, logistics_headers)
    ob_id, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"], shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": qty}])
    assert conf.status_code == 200, conf.text
    amount = round(float(unit_price) * qty, 2)
    return ctx, ob_id, amount


async def make_open_payable(client, db_session, sales_headers, purchaser_headers, *,
                            po_price="5.00", received=10, sku_codes=("SKUFIN_P",)):
    """造一张 UNPAID 应付:走采购→收货链(入库确认 @ 收货生成应付)。
    返回 (ctx, supplier_id, payable_id, amount)。payable.currency = USD(PO 币种)。"""
    ctx = await setup_available_stock(client, db_session, sales_headers, purchaser_headers,
                                      sku_codes=sku_codes, so_qty=received, unit_price="9.00",
                                      po_price=po_price, received=received)
    pays = (await client.get("/api/v1/payables", headers=purchaser_headers)
            ).json()["data"]["items"]
    row = next(it for it in pays if it["inbound_order_id"] == ctx["inbound_order_id"])
    return ctx, row["supplier_id"], row["id"], float(row["amount_original"])
