import pytest
from sqlalchemy import func, select

from app.db.models.ap_credit_memo import APCreditMemo, APCreditMemoStatus
from app.db.models.inbound_order import InboundOrder
from app.db.models.payable import Payable
from app.db.models.stock import InventoryBalance, InventoryMovement, InventoryMovementType
from tests.outbound_helpers import create_outbound, create_shipment, setup_available_stock

pytestmark = pytest.mark.asyncio


async def _inbound_line_id(client, purchaser_headers, inbound_order_id):
    detail = (await client.get(f"/api/v1/inbound-orders/{inbound_order_id}",
                               headers=purchaser_headers)).json()["data"]
    return detail["lines"][0]["id"]


async def test_purchase_return_flow_separates_approval_stock_and_ap_credit_memo(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_A",))
    inbound_line_id = await _inbound_line_id(client, purchaser_headers, ctx["inbound_order_id"])

    created = await client.post("/api/v1/purchase-returns", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "reason": "供应商接受退回",
        "lines": [{"inbound_order_line_id": inbound_line_id, "qty": 4}],
    })
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["order"]["no"].startswith("PR")
    assert data["order"]["status"] == "PENDING_APPROVAL"
    assert data["order"]["total_amount"] == 20.0
    assert data["lines"][0]["qty"] == 4.0
    assert data["lines"][0]["line_total"] == 20.0
    assert data["ap_credit_memo"] is None

    payable = (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == ctx["inbound_order_id"])
    )).scalar_one()
    assert float(payable.amount_original) == 50.0
    assert float(payable.amount_credited) == 0.0
    assert float(payable.amount_outstanding) == 50.0

    balance = (await db_session.execute(
        select(InventoryBalance).where(
            InventoryBalance.sales_order_id == ctx["sales_order_id"],
            InventoryBalance.sku_id == ctx["skus"][0].id,
        )
    )).scalar_one()
    assert float(balance.available_qty) == 10.0

    approved = await client.post(
        f"/api/v1/purchase-returns/{data['order']['id']}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "APPROVED"
    assert float(balance.available_qty) == 10.0

    returned = await client.post(
        f"/api/v1/purchase-returns/{data['order']['id']}/confirm-return-shipment",
        headers=purchaser_headers,
        json={"return_shipment_reference": "RTN-001"},
    )
    assert returned.status_code == 200, returned.text
    returned_data = returned.json()["data"]
    assert returned_data["order"]["status"] == "RETURNED"
    assert returned_data["ap_credit_memo"]["no"].startswith("APCM")
    assert returned_data["ap_credit_memo"]["status"] == "PENDING_APPROVAL"
    assert returned_data["ap_credit_memo"]["amount"] == 20.0

    await db_session.refresh(payable)
    await db_session.refresh(balance)
    assert float(payable.amount_credited) == 0.0
    assert float(payable.amount_outstanding) == 50.0
    assert float(balance.inbound_qty) == 6.0
    assert float(balance.outbound_qty) == 0.0
    assert float(balance.available_qty) == 6.0

    movement = (await db_session.execute(
        select(InventoryMovement)
        .where(InventoryMovement.movement_type == InventoryMovementType.PURCHASE_RETURN_ISSUE)
    )).scalar_one()
    assert movement.source_type == "PURCHASE_RETURN_ORDER"
    assert movement.source_id == data["order"]["id"]
    assert float(movement.qty_delta) == -4.0

    memo = (await db_session.execute(select(APCreditMemo))).scalar_one()
    assert memo.payable_id == payable.id
    assert memo.purchase_return_order_id == data["order"]["id"]
    assert memo.status == APCreditMemoStatus.PENDING_APPROVAL

    posted = await client.post(
        f"/api/v1/ap-credit-memos/{memo.id}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["data"]["status"] == "POSTED"

    await db_session.refresh(payable)
    assert float(payable.amount_credited) == 20.0
    assert float(payable.amount_allocated) == 0.0
    assert float(payable.amount_outstanding) == 30.0

    pays = (await client.get("/api/v1/payables", headers=purchaser_headers)
            ).json()["data"]["items"]
    row = next(it for it in pays if it["id"] == payable.id)
    assert row["amount_credited"] == 20.0
    assert row["amount_outstanding"] == 30.0
    assert row["status"] == "UNPAID"


async def test_purchase_return_reserves_qty_before_physical_return(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_B",))
    inbound_line_id = await _inbound_line_id(client, purchaser_headers, ctx["inbound_order_id"])

    ok = await client.post("/api/v1/purchase-returns", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "lines": [{"inbound_order_line_id": inbound_line_id, "qty": 4}],
    })
    assert ok.status_code == 200, ok.text

    lines = (await client.get(
        f"/api/v1/purchase-returns/returnable-lines?inbound_order_id={ctx['inbound_order_id']}",
        headers=purchaser_headers,
    )).json()["data"]["items"]
    assert lines[0]["returned_qty"] == 0.0
    assert lines[0]["in_process_return_qty"] == 4.0
    assert lines[0]["returnable_qty"] == 6.0

    over = await client.post("/api/v1/purchase-returns", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "lines": [{"inbound_order_line_id": inbound_line_id, "qty": 7}],
    })
    assert over.status_code == 409
    assert over.json()["code"] == 41715


async def test_purchase_return_rejects_when_outbound_order_exists(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_C",))
    ship = await create_shipment(client, logistics_headers)
    draft = await create_outbound(
        client, logistics_headers,
        sales_order_id=ctx["sales_order_id"],
        shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 1}],
    )
    assert draft.status_code == 200, draft.text

    inbound_line_id = await _inbound_line_id(client, purchaser_headers, ctx["inbound_order_id"])
    r = await client.post("/api/v1/purchase-returns", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "lines": [{"inbound_order_line_id": inbound_line_id, "qty": 1}],
    })
    assert r.status_code == 409
    assert r.json()["code"] == 41714


async def test_in_transit_cancellation_creates_ap_credit_without_stock_movement(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_D",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]
    inbound_line_id = created_inbound.json()["data"]["lines"][0]["id"]

    payable = (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inbound_id)
    )).scalar_one()
    assert float(payable.amount_original) == 50.0
    assert float(payable.amount_credited) == 0.0
    assert float(payable.amount_outstanding) == 50.0

    created = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id, "reason": "供应商接受在途取消"},
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["order"]["status"] == "PENDING_APPROVAL"
    assert data["order"]["total_amount"] == 50.0
    assert data["lines"][0]["inbound_order_line_id"] == inbound_line_id
    assert data["lines"][0]["qty"] == 10.0
    assert data["ap_credit_memo"] is None

    approved = await client.post(
        f"/api/v1/purchase-returns/{data['order']['id']}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text

    confirmed = await client.post(
        f"/api/v1/purchase-returns/{data['order']['id']}/confirm-in-transit-cancellation",
        headers=purchaser_headers,
        json={"cancellation_reference": "SUP-CXL-001", "cancellation_note": "未入库取消"},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_data = confirmed.json()["data"]
    assert confirmed_data["order"]["status"] == "RETURNED"
    assert confirmed_data["order"]["return_shipment_reference"] == "SUP-CXL-001"
    assert confirmed_data["order"]["return_note"] == "未入库取消"
    assert confirmed_data["ap_credit_memo"]["status"] == "PENDING_APPROVAL"
    assert confirmed_data["ap_credit_memo"]["amount"] == 50.0

    inbound = (await db_session.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_id)
    )).scalar_one()
    assert inbound.status == "CANCELLED"

    movement_count = (await db_session.execute(
        select(func.count(InventoryMovement.id))
    )).scalar_one()
    assert movement_count == 0
    balance = (await db_session.execute(
        select(InventoryBalance).where(
            InventoryBalance.sales_order_id == ctx["sales_order_id"],
            InventoryBalance.sku_id == ctx["skus"][0].id,
        )
    )).scalar_one_or_none()
    assert balance is None

    await db_session.refresh(payable)
    assert float(payable.amount_credited) == 0.0
    assert float(payable.amount_outstanding) == 50.0

    memo = (await db_session.execute(select(APCreditMemo))).scalar_one()
    posted = await client.post(
        f"/api/v1/ap-credit-memos/{memo.id}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text
    await db_session.refresh(payable)
    assert float(payable.amount_credited) == 50.0
    assert float(payable.amount_outstanding) == 0.0

    reopened = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert reopened.status_code == 200, reopened.text


async def test_in_transit_cancellation_requires_unreceived_inbound(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_E",))

    r = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": ctx["inbound_order_id"]},
    )
    assert r.status_code == 409
    assert r.json()["code"] == 41714


async def test_pending_in_transit_cancellation_blocks_receive(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_F",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]

    created_reverse = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id, "reason": "供应商接受在途取消"},
    )
    assert created_reverse.status_code == 200, created_reverse.text

    received = await client.post(
        f"/api/v1/inbound-orders/{inbound_id}/receive",
        headers=purchaser_headers,
        json={},
    )
    assert received.status_code == 409
    assert received.json()["code"] == 41712


async def test_pending_purchase_return_blocks_unreceive(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_G",))
    inbound_line_id = await _inbound_line_id(client, purchaser_headers, ctx["inbound_order_id"])

    created_reverse = await client.post("/api/v1/purchase-returns", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "reason": "供应商接受退回",
        "lines": [{"inbound_order_line_id": inbound_line_id, "qty": 4}],
    })
    assert created_reverse.status_code == 200, created_reverse.text

    unreceived = await client.post(
        f"/api/v1/inbound-orders/{ctx['inbound_order_id']}/unreceive",
        headers=purchaser_headers,
        json={},
    )
    assert unreceived.status_code == 409
    assert unreceived.json()["code"] == 41712
