from decimal import Decimal

import pytest
from sqlalchemy import event, func, select

from app.audit.constants import AuditAction, AuditResourceType
from app.db.models.ap_credit_memo import APCreditMemo, APCreditMemoStatus
from app.db.models.audit_log import AuditLog
from app.db.models.company_loss import CompanyLossEntry
from app.db.models.customer_refund import CustomerRefund
from app.db.models.inbound_order import InboundOrder
from app.db.models.payable import Payable
from app.db.models.payment import Payment
from app.db.models.payment_allocation import PaymentAllocation
from app.db.models.purchase_return import PurchaseReturnKind, PurchaseReturnOrder
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
    assert data["order"]["return_kind"] == "PURCHASE_RETURN"
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
    assert data["order"]["return_kind"] == "IN_TRANSIT_CANCELLATION"
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

    duplicate_confirm = await client.post(
        f"/api/v1/purchase-returns/{data['order']['id']}/confirm-in-transit-cancellation",
        headers=purchaser_headers,
        json={},
    )
    assert duplicate_confirm.status_code == 409
    assert duplicate_confirm.json()["code"] == 41714

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
    duplicate_post = await client.post(
        f"/api/v1/ap-credit-memos/{memo.id}/post",
        headers=finance_headers,
        json={},
    )
    assert duplicate_post.status_code == 409
    assert duplicate_post.json()["code"] == 41714
    await db_session.refresh(payable)
    assert float(payable.amount_credited) == 50.0
    assert float(payable.amount_outstanding) == 0.0

    reopened = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert reopened.status_code == 200, reopened.text


async def test_company_assumed_cancellation_received_holds_stock_and_preserves_ap(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_CA",))

    created = await client.post(
        "/api/v1/purchase-returns/company-assumed-cancellations",
        headers=purchaser_headers,
        json={
            "inbound_order_id": ctx["inbound_order_id"],
            "reason": "供应商不接受,公司承担",
            "customer_refund_amount": 12.5,
        },
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["order"]["return_kind"] == "COMPANY_ASSUMED_CANCELLATION"
    assert data["order"]["status"] == "PENDING_APPROVAL"
    assert data["order"]["total_amount"] == 50.0
    assert data["order"]["customer_refund_amount"] == 12.5
    assert data["order"]["company_loss_amount"] == 62.5
    assert data["ap_credit_memo"] is None
    assert data["customer_refund"] is None
    assert data["company_loss_entry"] is None

    approved = await client.post(
        f"/api/v1/purchase-returns/{data['order']['id']}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text

    confirmed = await client.post(
        f"/api/v1/purchase-returns/{data['order']['id']}/confirm-company-assumed-cancellation",
        headers=purchaser_headers,
        json={"cancellation_reference": "CA-001", "cancellation_note": "转待处置"},
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_data = confirmed.json()["data"]
    assert confirmed_data["order"]["status"] == "COMPLETED"
    assert confirmed_data["ap_credit_memo"] is None
    assert confirmed_data["customer_refund"]["no"].startswith("CRF")
    assert confirmed_data["customer_refund"]["status"] == "PENDING_PAYMENT"
    assert confirmed_data["customer_refund"]["amount"] == 12.5
    assert confirmed_data["company_loss_entry"]["no"].startswith("CL")
    assert confirmed_data["company_loss_entry"]["status"] == "POSTED"
    assert confirmed_data["company_loss_entry"]["amount"] == 62.5

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
    await db_session.refresh(balance)
    assert float(balance.inbound_qty) == 10.0
    assert float(balance.outbound_qty) == 0.0
    assert float(balance.disposition_qty) == 10.0
    assert float(balance.available_qty) == 0.0

    movement = (await db_session.execute(
        select(InventoryMovement).where(
            InventoryMovement.movement_type
            == InventoryMovementType.COMPANY_DISPOSITION_HOLD
        )
    )).scalar_one()
    assert movement.source_type == "PURCHASE_RETURN_ORDER"
    assert movement.source_id == data["order"]["id"]
    assert float(movement.qty_delta) == -10.0
    assert (await db_session.execute(select(func.count(APCreditMemo.id)))).scalar_one() == 0
    assert (await db_session.execute(select(func.count(CustomerRefund.id)))).scalar_one() == 1
    assert (await db_session.execute(select(func.count(CompanyLossEntry.id)))).scalar_one() == 1

    duplicate_confirm = await client.post(
        f"/api/v1/purchase-returns/{data['order']['id']}/confirm-company-assumed-cancellation",
        headers=purchaser_headers,
        json={},
    )
    assert duplicate_confirm.status_code == 409


async def test_company_assumed_cancellation_in_transit_closes_inbound_without_stock_or_ap_credit(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_CB",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]

    created = await client.post(
        "/api/v1/purchase-returns/company-assumed-cancellations",
        headers=purchaser_headers,
        json={
            "inbound_order_id": inbound_id,
            "reason": "供应商不接受取消但公司退款",
            "customer_refund_amount": 0,
        },
    )
    assert created.status_code == 200, created.text
    order_id = created.json()["data"]["order"]["id"]

    receive_blocked = await client.post(
        f"/api/v1/inbound-orders/{inbound_id}/receive",
        headers=purchaser_headers,
        json={},
    )
    assert receive_blocked.status_code == 409

    approved = await client.post(
        f"/api/v1/purchase-returns/{order_id}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    confirmed = await client.post(
        f"/api/v1/purchase-returns/{order_id}/confirm-company-assumed-cancellation",
        headers=purchaser_headers,
        json={"cancellation_reference": "CA-INTRANSIT"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["order"]["status"] == "COMPLETED"
    assert confirmed.json()["data"]["customer_refund"] is None
    assert confirmed.json()["data"]["company_loss_entry"]["amount"] == 50.0

    inbound = (await db_session.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_id)
    )).scalar_one()
    assert inbound.status == "CANCELLED"
    payable = (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inbound_id)
    )).scalar_one()
    assert float(payable.amount_credited) == 0.0
    assert float(payable.amount_outstanding) == 50.0
    assert (await db_session.execute(select(func.count(APCreditMemo.id)))).scalar_one() == 0
    assert (await db_session.execute(select(func.count(InventoryMovement.id)))).scalar_one() == 0


async def test_rejected_in_transit_credit_memo_can_be_resubmitted_without_reopening_flow(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_Q",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]
    payable = (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inbound_id)
    )).scalar_one()

    created = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id, "reason": "供应商接受取消"},
    )
    assert created.status_code == 200, created.text
    order_id = created.json()["data"]["order"]["id"]
    approved = await client.post(
        f"/api/v1/purchase-returns/{order_id}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    confirmed = await client.post(
        f"/api/v1/purchase-returns/{order_id}/confirm-in-transit-cancellation",
        headers=purchaser_headers,
        json={},
    )
    assert confirmed.status_code == 200, confirmed.text
    old_memo_id = confirmed.json()["data"]["ap_credit_memo"]["id"]

    rejected = await client.post(
        f"/api/v1/ap-credit-memos/{old_memo_id}/reject",
        headers=finance_headers,
        json={"reject_reason": "供应商贷项凭证信息不完整"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "REJECTED"

    old_post = await client.post(
        f"/api/v1/ap-credit-memos/{old_memo_id}/post",
        headers=finance_headers,
        json={},
    )
    assert old_post.status_code == 409
    assert old_post.json()["code"] == 41714

    resubmitted = await client.post(
        f"/api/v1/ap-credit-memos/{old_memo_id}/resubmit",
        headers=finance_headers,
        json={},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    new_memo = resubmitted.json()["data"]
    assert new_memo["id"] != old_memo_id
    assert new_memo["status"] == "PENDING_APPROVAL"
    assert new_memo["purchase_return_order_id"] == order_id
    assert new_memo["payable_id"] == payable.id
    assert new_memo["amount"] == 50.0

    duplicate_resubmit = await client.post(
        f"/api/v1/ap-credit-memos/{old_memo_id}/resubmit",
        headers=finance_headers,
        json={},
    )
    assert duplicate_resubmit.status_code == 409
    assert duplicate_resubmit.json()["code"] == 41714

    detail = await client.get(f"/api/v1/purchase-returns/{order_id}", headers=purchaser_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["ap_credit_memo"]["id"] == new_memo["id"]
    rows = (await client.get(
        f"/api/v1/purchase-returns?inbound_order_id={inbound_id}",
        headers=purchaser_headers,
    )).json()["data"]["items"]
    assert rows[0]["ap_credit_memo_status"] == "PENDING_APPROVAL"

    posted = await client.post(
        f"/api/v1/ap-credit-memos/{new_memo['id']}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text
    await db_session.refresh(payable)
    assert float(payable.amount_credited) == 50.0
    assert float(payable.amount_outstanding) == 0.0

    inbound = (await db_session.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_id)
    )).scalar_one()
    assert inbound.status == "CANCELLED"
    movement_count = (await db_session.execute(
        select(func.count(InventoryMovement.id))
    )).scalar_one()
    assert movement_count == 0

    memos = (await db_session.execute(
        select(APCreditMemo)
        .where(APCreditMemo.purchase_return_order_id == order_id)
        .order_by(APCreditMemo.id)
    )).scalars().all()
    assert [memo.status for memo in memos] == [
        APCreditMemoStatus.REJECTED,
        APCreditMemoStatus.POSTED,
    ]
    resubmit_audit = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.resource_type == AuditResourceType.AP_CREDIT_MEMO.value,
            AuditLog.resource_id == str(new_memo["id"]),
            AuditLog.action == AuditAction.CREATE.value,
        )
    )).scalar_one()
    assert resubmit_audit.extra["resubmitted_from_ap_credit_memo_id"] == old_memo_id
    assert resubmit_audit.extra["return_kind"] == "IN_TRANSIT_CANCELLATION"


async def test_in_transit_cancellation_reject_unlocks_resubmission_and_receive(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_H",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]

    first = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id, "reason": "首次提交"},
    )
    assert first.status_code == 200, first.text

    duplicate = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id, "reason": "重复提交"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == 41714

    rejected = await client.post(
        f"/api/v1/purchase-returns/{first.json()['data']['order']['id']}/reject",
        headers=purchaser_headers,
        json={"reject_reason": "供应商改为继续发货"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "REJECTED"

    second = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id, "reason": "供应商再次接受取消"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["data"]["order"]["return_kind"] == "IN_TRANSIT_CANCELLATION"
    rejected_again = await client.post(
        f"/api/v1/purchase-returns/{second.json()['data']['order']['id']}/reject",
        headers=purchaser_headers,
        json={"reject_reason": "保留在途入库"},
    )
    assert rejected_again.status_code == 200, rejected_again.text

    received = await client.post(
        f"/api/v1/inbound-orders/{inbound_id}/receive",
        headers=purchaser_headers,
        json={},
    )
    assert received.status_code == 200, received.text


async def test_approved_in_transit_cancellation_blocks_duplicate_submission(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_M",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]

    first = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id},
    )
    assert first.status_code == 200, first.text
    approved = await client.post(
        f"/api/v1/purchase-returns/{first.json()['data']['order']['id']}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text

    duplicate = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == 41714


async def test_in_transit_cancellation_rejects_when_outbound_order_exists(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_N",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]
    ship = await create_shipment(client, logistics_headers)
    draft = await create_outbound(
        client, logistics_headers,
        sales_order_id=ctx["sales_order_id"],
        shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 1}],
    )
    assert draft.status_code == 200, draft.text

    blocked = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == 41714


async def test_zero_amount_in_transit_cancellation_creates_no_credit_memo(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="0.00", received=0, sku_codes=("SKUPR_O",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]

    created = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id},
    )
    assert created.status_code == 200, created.text
    order_id = created.json()["data"]["order"]["id"]
    assert created.json()["data"]["order"]["total_amount"] == 0.0

    approved = await client.post(
        f"/api/v1/purchase-returns/{order_id}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    confirmed = await client.post(
        f"/api/v1/purchase-returns/{order_id}/confirm-in-transit-cancellation",
        headers=purchaser_headers,
        json={},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["ap_credit_memo"] is None
    memo_count = (await db_session.execute(select(func.count(APCreditMemo.id)))).scalar_one()
    assert memo_count == 0


async def test_purchase_return_confirm_in_transit_endpoint_rejects_normal_return(
        client, db_session, sales_headers, purchaser_headers):
    received_ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_I",))
    inbound_line_id = await _inbound_line_id(
        client, purchaser_headers, received_ctx["inbound_order_id"])
    normal = await client.post("/api/v1/purchase-returns", headers=purchaser_headers, json={
        "inbound_order_id": received_ctx["inbound_order_id"],
        "lines": [{"inbound_order_line_id": inbound_line_id, "qty": 1}],
    })
    assert normal.status_code == 200, normal.text
    normal_id = normal.json()["data"]["order"]["id"]
    approved_normal = await client.post(
        f"/api/v1/purchase-returns/{normal_id}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved_normal.status_code == 200, approved_normal.text
    wrong_normal = await client.post(
        f"/api/v1/purchase-returns/{normal_id}/confirm-in-transit-cancellation",
        headers=purchaser_headers,
        json={},
    )
    assert wrong_normal.status_code == 409
    assert wrong_normal.json()["code"] == 41714


async def test_in_transit_confirm_return_shipment_endpoint_rejects_cancellation(
        client, db_session, sales_headers, purchaser_headers):
    in_transit_ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_J",))
    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": in_transit_ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": in_transit_ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    in_transit_id = created_inbound.json()["data"]["order"]["id"]
    cancellation = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": in_transit_id},
    )
    assert cancellation.status_code == 200, cancellation.text
    cancellation_id = cancellation.json()["data"]["order"]["id"]
    approved_cancellation = await client.post(
        f"/api/v1/purchase-returns/{cancellation_id}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved_cancellation.status_code == 200, approved_cancellation.text
    wrong_cancellation = await client.post(
        f"/api/v1/purchase-returns/{cancellation_id}/confirm-return-shipment",
        headers=purchaser_headers,
        json={},
    )
    assert wrong_cancellation.status_code == 409
    assert wrong_cancellation.json()["code"] == 41714


async def test_credit_memo_post_releases_paid_payable_to_supplier_prepayment(
        client, db_session, _connection, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=0, sku_codes=("SKUPR_K",))

    created_inbound = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": ctx["purchase_order_id"],
        "lines": [{"purchase_order_line_id": ctx["po_lines"][0]["id"], "qty": 10}],
    })
    assert created_inbound.status_code == 200, created_inbound.text
    inbound_id = created_inbound.json()["data"]["order"]["id"]
    payable = (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == inbound_id)
    )).scalar_one()

    payment_resp = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": payable.supplier_id,
        "currency": payable.currency,
        "amount": "50.00",
        "paid_at": "2026-07-21",
    })
    assert payment_resp.status_code == 200, payment_resp.text
    payment_id = payment_resp.json()["data"]["payment"]["id"]
    allocation_id = payment_resp.json()["data"]["allocations"][0]["id"]
    await db_session.refresh(payable)
    assert float(payable.amount_allocated) == 50.0
    assert float(payable.amount_outstanding) == 0.0

    created = await client.post(
        "/api/v1/purchase-returns/in-transit-cancellations",
        headers=purchaser_headers,
        json={"inbound_order_id": inbound_id, "reason": "已付款后供应商接受取消"},
    )
    assert created.status_code == 200, created.text
    return_order_id = created.json()["data"]["order"]["id"]
    assert created.json()["data"]["order"]["return_kind"] == "IN_TRANSIT_CANCELLATION"
    approved = await client.post(
        f"/api/v1/purchase-returns/{return_order_id}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    confirmed = await client.post(
        f"/api/v1/purchase-returns/{return_order_id}/confirm-in-transit-cancellation",
        headers=purchaser_headers,
        json={},
    )
    assert confirmed.status_code == 200, confirmed.text
    memo_id = confirmed.json()["data"]["ap_credit_memo"]["id"]

    lock_order = []

    def capture_lock_order(conn, cursor, statement, parameters, context, executemany):
        sql = " ".join(statement.lower().split())
        if "for update" not in sql:
            return
        if "from payments" in sql:
            lock_order.append("payments")
        elif "from payables" in sql:
            lock_order.append("payables")
        elif "from payment_allocations" in sql:
            lock_order.append("payment_allocations")

    event.listen(_connection.sync_connection, "before_cursor_execute", capture_lock_order)
    try:
        posted = await client.post(
            f"/api/v1/ap-credit-memos/{memo_id}/post",
            headers=finance_headers,
            json={},
        )
    finally:
        event.remove(_connection.sync_connection, "before_cursor_execute", capture_lock_order)
    assert posted.status_code == 200, posted.text
    assert lock_order.index("payments") < lock_order.index("payables")
    assert lock_order.index("payables") < lock_order.index("payment_allocations")

    await db_session.refresh(payable)
    payment = (await db_session.execute(
        select(Payment).where(Payment.id == payment_id)
    )).scalar_one()
    old_allocation = (await db_session.execute(
        select(PaymentAllocation).where(PaymentAllocation.id == allocation_id)
    )).scalar_one()
    active_allocations = (await db_session.execute(
        select(func.count(PaymentAllocation.id)).where(
            PaymentAllocation.payable_id == payable.id,
            PaymentAllocation.reversed_at.is_(None),
        )
    )).scalar_one()
    assert float(payable.amount_allocated) == 0.0
    assert float(payable.amount_credited) == 50.0
    assert float(payable.amount_outstanding) == 0.0
    assert float(payment.amount_allocated) == 0.0
    assert float(payment.amount_unallocated) == 50.0
    assert old_allocation.reversed_at is not None
    assert active_allocations == 0

    memo = (await db_session.execute(
        select(APCreditMemo).where(APCreditMemo.id == memo_id)
    )).scalar_one()
    assert memo.purchase_return_order_id == return_order_id
    return_order = (await db_session.execute(
        select(PurchaseReturnOrder).where(PurchaseReturnOrder.id == return_order_id)
    )).scalar_one()
    assert return_order.return_kind == PurchaseReturnKind.IN_TRANSIT_CANCELLATION

    post_audit = (await db_session.execute(
        select(AuditLog).where(
            AuditLog.resource_type == AuditResourceType.AP_CREDIT_MEMO.value,
            AuditLog.resource_id == str(memo_id),
            AuditLog.action == AuditAction.POST.value,
        )
    )).scalar_one()
    assert post_audit.extra["purchase_return_order_id"] == return_order_id
    assert post_audit.extra["return_kind"] == "IN_TRANSIT_CANCELLATION"
    assert post_audit.extra["released_payment_allocations"][0]["payment_id"] == payment_id


async def test_credit_memo_post_partially_releases_payment_allocation(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_L",))
    inbound_line_id = await _inbound_line_id(client, purchaser_headers, ctx["inbound_order_id"])
    payable = (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == ctx["inbound_order_id"])
    )).scalar_one()

    payment_resp = await client.post("/api/v1/payments", headers=finance_headers, json={
        "supplier_id": payable.supplier_id,
        "currency": payable.currency,
        "amount": "50.00",
        "paid_at": "2026-07-21",
    })
    assert payment_resp.status_code == 200, payment_resp.text
    payment_id = payment_resp.json()["data"]["payment"]["id"]
    allocation_id = payment_resp.json()["data"]["allocations"][0]["id"]

    created = await client.post("/api/v1/purchase-returns", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "reason": "供应商接受部分退回",
        "lines": [{"inbound_order_line_id": inbound_line_id, "qty": 4}],
    })
    assert created.status_code == 200, created.text
    return_order_id = created.json()["data"]["order"]["id"]
    approved = await client.post(
        f"/api/v1/purchase-returns/{return_order_id}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    returned = await client.post(
        f"/api/v1/purchase-returns/{return_order_id}/confirm-return-shipment",
        headers=purchaser_headers,
        json={},
    )
    assert returned.status_code == 200, returned.text
    memo_id = returned.json()["data"]["ap_credit_memo"]["id"]

    posted = await client.post(
        f"/api/v1/ap-credit-memos/{memo_id}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text

    await db_session.refresh(payable)
    payment = (await db_session.execute(
        select(Payment).where(Payment.id == payment_id)
    )).scalar_one()
    old_allocation = (await db_session.execute(
        select(PaymentAllocation).where(PaymentAllocation.id == allocation_id)
    )).scalar_one()
    active_allocation = (await db_session.execute(
        select(PaymentAllocation).where(
            PaymentAllocation.payable_id == payable.id,
            PaymentAllocation.reversed_at.is_(None),
        )
    )).scalar_one()
    assert float(payable.amount_allocated) == 30.0
    assert float(payable.amount_credited) == 20.0
    assert float(payable.amount_outstanding) == 0.0
    assert float(payment.amount_allocated) == 30.0
    assert float(payment.amount_unallocated) == 20.0
    assert old_allocation.reversed_at is not None
    assert active_allocation.id != allocation_id
    assert float(active_allocation.amount) == 30.0


async def test_credit_memo_post_rejects_amount_above_original_payable(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUPR_P",))
    inbound_line_id = await _inbound_line_id(client, purchaser_headers, ctx["inbound_order_id"])

    created = await client.post("/api/v1/purchase-returns", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "lines": [{"inbound_order_line_id": inbound_line_id, "qty": 4}],
    })
    assert created.status_code == 200, created.text
    order_id = created.json()["data"]["order"]["id"]
    approved = await client.post(
        f"/api/v1/purchase-returns/{order_id}/approve",
        headers=purchaser_headers,
        json={},
    )
    assert approved.status_code == 200, approved.text
    returned = await client.post(
        f"/api/v1/purchase-returns/{order_id}/confirm-return-shipment",
        headers=purchaser_headers,
        json={},
    )
    assert returned.status_code == 200, returned.text
    memo_id = returned.json()["data"]["ap_credit_memo"]["id"]

    memo = (await db_session.execute(
        select(APCreditMemo).where(APCreditMemo.id == memo_id)
    )).scalar_one()
    memo.amount = Decimal("60.00")
    await db_session.commit()

    posted = await client.post(
        f"/api/v1/ap-credit-memos/{memo_id}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 409
    assert posted.json()["code"] == 41717


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
