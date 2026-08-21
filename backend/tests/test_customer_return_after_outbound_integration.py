"""出库后客户退货:原正向链路不回滚,退回货进入售后待处置库存。"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models.customer_return import CustomerReturnOrder
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.receivable import Receivable
from app.db.models.stock import InventoryBalance, InventoryMovement, InventoryMovementType
from tests.outbound_helpers import (
    create_and_confirm_outbound,
    create_shipment,
    setup_available_stock,
)

pytestmark = pytest.mark.asyncio


async def _issued_outbound_ctx(client, db_session, sales_headers, purchaser_headers,
                               logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        sku_codes=("SKU_CUSTOMER_RETURN",), so_qty=10, unit_price="9.00",
        po_price="5.00", received=10)
    ship = await create_shipment(client, logistics_headers)
    outbound_id, confirmed = await create_and_confirm_outbound(
        client, logistics_headers,
        sales_order_id=ctx["sales_order_id"],
        shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 8}],
    )
    assert confirmed.status_code == 200, confirmed.text
    return {**ctx, "shipment": ship, "outbound_id": outbound_id}


async def _load_shipment(client, logistics_headers, shipment: dict) -> dict:
    loaded = await client.post(
        f"/api/v1/shipments/{shipment['id']}/load",
        headers=logistics_headers,
        json={"expected_updated_at": shipment["updated_at"]},
    )
    assert loaded.status_code == 200, loaded.text
    return loaded.json()["data"]["shipment"]


async def test_customer_return_receives_into_disposition_without_reverting_outbound_or_ar(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await _issued_outbound_ctx(
        client, db_session, sales_headers, purchaser_headers, logistics_headers)
    await _load_shipment(client, logistics_headers, ctx["shipment"])
    outbound_id = ctx["outbound_id"]
    outbound_line_id = (await client.get(
        f"/api/v1/outbound-orders/{outbound_id}", headers=logistics_headers
    )).json()["data"]["lines"][0]["id"]

    created = await client.post("/api/v1/customer-returns", headers=logistics_headers, json={
        "outbound_order_id": outbound_id,
        "reason": "客户退回,供应商结论待定",
        "lines": [{"outbound_order_line_id": outbound_line_id, "qty": "3"}],
    })
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["order"]["outbound_order_id"] == outbound_id
    assert data["order"]["sales_order_id"] == ctx["sales_order_id"]
    assert data["trace"]["purchase_order_ids"] == [ctx["purchase_order_id"]]
    assert data["trace"]["inbound_order_ids"] == [ctx["inbound_order_id"]]

    outbound = (await db_session.execute(
        select(OutboundOrder).where(OutboundOrder.id == outbound_id)
    )).scalar_one()
    assert outbound.status == OutboundOrderStatus.ISSUED
    receivable = (await db_session.execute(
        select(Receivable).where(Receivable.outbound_order_id == outbound_id)
    )).scalar_one()
    assert Decimal(str(receivable.amount_original)) == Decimal("72.00")
    assert receivable.voided_at is None

    balance = (await db_session.execute(
        select(InventoryBalance).where(
            InventoryBalance.sales_order_id == ctx["sales_order_id"],
            InventoryBalance.sku_id == ctx["skus"][0].id,
        )
    )).scalar_one()
    assert Decimal(str(balance.inbound_qty)) == Decimal("13.000")
    assert Decimal(str(balance.outbound_qty)) == Decimal("8.000")
    assert Decimal(str(balance.disposition_qty)) == Decimal("3.000")
    assert Decimal(str(balance.available_qty)) == Decimal("2.000")

    movement = (await db_session.execute(
        select(InventoryMovement)
        .where(InventoryMovement.movement_type == InventoryMovementType.CUSTOMER_RETURN_RECEIVE)
    )).scalar_one()
    assert Decimal(str(movement.qty_delta)) == Decimal("3.000")
    assert movement.source_type == "CUSTOMER_RETURN_ORDER"
    assert movement.source_id == data["order"]["id"]


async def test_customer_return_rejects_cumulative_over_return(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await _issued_outbound_ctx(
        client, db_session, sales_headers, purchaser_headers, logistics_headers)
    await _load_shipment(client, logistics_headers, ctx["shipment"])
    outbound_id = ctx["outbound_id"]
    outbound_line_id = (await client.get(
        f"/api/v1/outbound-orders/{outbound_id}", headers=logistics_headers
    )).json()["data"]["lines"][0]["id"]

    first = await client.post("/api/v1/customer-returns", headers=logistics_headers, json={
        "outbound_order_id": outbound_id,
        "lines": [{"outbound_order_line_id": outbound_line_id, "qty": "6"}],
    })
    assert first.status_code == 200, first.text

    second = await client.post("/api/v1/customer-returns", headers=logistics_headers, json={
        "outbound_order_id": outbound_id,
        "lines": [{"outbound_order_line_id": outbound_line_id, "qty": "3"}],
    })
    assert second.status_code == 409
    assert second.json()["code"] == 42302

    rows = (await db_session.execute(select(CustomerReturnOrder))).scalars().all()
    assert len(rows) == 1


async def test_customer_return_rejects_open_shipment(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await _issued_outbound_ctx(
        client, db_session, sales_headers, purchaser_headers, logistics_headers)
    outbound_id = ctx["outbound_id"]
    outbound_line_id = (await client.get(
        f"/api/v1/outbound-orders/{outbound_id}", headers=logistics_headers
    )).json()["data"]["lines"][0]["id"]

    created = await client.post("/api/v1/customer-returns", headers=logistics_headers, json={
        "outbound_order_id": outbound_id,
        "lines": [{"outbound_order_line_id": outbound_line_id, "qty": "1"}],
    })
    assert created.status_code == 409
    assert created.json()["code"] == 42301
