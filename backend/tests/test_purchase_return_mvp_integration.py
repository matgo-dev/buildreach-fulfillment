import pytest
from sqlalchemy import select

from app.db.models.ap_credit_memo import APCreditMemo, APCreditMemoStatus
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
