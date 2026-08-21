from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models.ap_credit_memo import APCreditMemo
from app.db.models.customer_credit_memo import (
    CustomerCreditAllocation,
    CustomerCreditMemo,
    CustomerCreditMemoStatus,
    CustomerCreditMemoType,
)
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.payable import Payable
from app.db.models.receivable import Receivable
from app.services import customer_credit_memo_service
from tests.outbound_helpers import create_shipment, setup_available_stock

pytestmark = pytest.mark.asyncio


async def _create_held_disposition(client, purchaser_headers, inbound_order_id: int) -> dict:
    created = await client.post(
        "/api/v1/inventory-dispositions",
        headers=purchaser_headers,
        json={
            "inbound_order_id": inbound_order_id,
            "receipt_handling": "RECEIVE_TO_DISPOSITION",
            "reason": "供应商不接受,客户侧挂余额",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["data"]


async def _direct_cny_receivable(
    db_session, *, sales_order_id: int, customer_id: int, shipment_id: int, amount: str = "100.00",
) -> Receivable:
    outbound = OutboundOrder(
        no=f"OBCCM{sales_order_id}{shipment_id}",
        sales_order_id=sales_order_id,
        shipment_id=shipment_id,
        status=OutboundOrderStatus.ISSUED,
        created_by=1,
    )
    db_session.add(outbound)
    await db_session.flush()
    receivable = Receivable(
        outbound_order_id=outbound.id,
        sales_order_id=sales_order_id,
        customer_id=customer_id,
        currency="CNY",
        amount_original=Decimal(amount),
        amount_allocated=Decimal("0.00"),
        created_by=1,
    )
    db_session.add(receivable)
    await db_session.commit()
    await db_session.refresh(receivable)
    return receivable


async def test_customer_credit_memo_posts_cny_balance_without_touching_supplier_ap(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUCCM_A",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])

    payable = (await db_session.execute(
        select(Payable).where(Payable.inbound_order_id == ctx["inbound_order_id"])
    )).scalar_one()
    before_credited = Decimal(str(payable.amount_credited))
    before_outstanding = Decimal(str(payable.amount_outstanding))

    created = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={
            "inventory_disposition_order_id": disposition["order"]["id"],
            "amount": "123.45",
            "currency": "CNY",
            "reason": "给客户挂人民币余额",
        },
    )
    assert created.status_code == 200, created.text
    memo = created.json()["data"]
    assert memo["no"].startswith("CCM")
    assert memo["status"] == "PENDING_APPROVAL"
    assert memo["currency"] == "CNY"
    assert Decimal(str(memo["amount"])) == Decimal("123.45")

    no_finance_post = await client.post(
        f"/api/v1/customer-credit-memos/{memo['id']}/post",
        headers=purchaser_headers,
        json={},
    )
    assert no_finance_post.status_code == 403

    posted = await client.post(
        f"/api/v1/customer-credit-memos/{memo['id']}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text
    posted_memo = posted.json()["data"]
    assert posted_memo["status"] == "POSTED"
    assert Decimal(str(posted_memo["amount_unallocated"])) == Decimal("123.45")

    await db_session.refresh(payable)
    assert Decimal(str(payable.amount_credited)) == before_credited
    assert Decimal(str(payable.amount_outstanding)) == before_outstanding
    assert (await db_session.execute(select(func.count(APCreditMemo.id)))).scalar_one() == 0

    balance = await customer_credit_memo_service.posted_unallocated_balance(
        db_session, customer_id=ctx["customer"].id)
    assert balance == Decimal("123.45")

    detail = await client.get(
        f"/api/v1/inventory-dispositions/by-inbound/{ctx['inbound_order_id']}",
        headers=purchaser_headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["customer_credit_memo"]["id"] == memo["id"]


async def test_customer_credit_memo_reject_resubmit_and_active_unique(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUCCM_B",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    disposition_id = disposition["order"]["id"]

    first = await client.post(
        "/api/v1/customer-credit-memos",
        headers=sales_headers,
        json={"inventory_disposition_order_id": disposition_id, "amount": "88.00"},
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["data"]["id"]

    duplicate = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disposition_id, "amount": "88.00"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == 41714

    rejected = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/reject",
        headers=finance_headers,
        json={"reject_reason": "补偿依据不完整"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "REJECTED"

    old_post = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/post",
        headers=finance_headers,
        json={},
    )
    assert old_post.status_code == 409

    resubmitted = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/resubmit",
        headers=sales_headers,
        json={"amount": "66.00", "reason": "补充材料后重提"},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    new_id = resubmitted.json()["data"]["id"]
    assert new_id != first_id
    assert resubmitted.json()["data"]["status"] == "PENDING_APPROVAL"
    assert resubmitted.json()["data"]["resubmitted_from_id"] == first_id
    assert Decimal(str(resubmitted.json()["data"]["amount"])) == Decimal("66.00")

    duplicate_resubmit = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/resubmit",
        headers=sales_headers,
        json={"amount": "66.00"},
    )
    assert duplicate_resubmit.status_code == 409

    posted = await client.post(
        f"/api/v1/customer-credit-memos/{new_id}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text

    memos = (await db_session.execute(
        select(CustomerCreditMemo)
        .where(CustomerCreditMemo.inventory_disposition_order_id == disposition_id)
        .order_by(CustomerCreditMemo.id)
    )).scalars().all()
    assert [m.status for m in memos] == [
        CustomerCreditMemoStatus.REJECTED,
        CustomerCreditMemoStatus.POSTED,
    ]


async def test_customer_credit_memo_allocates_to_receivable_and_can_reverse_then_void(
        client, db_session, sales_headers, purchaser_headers, finance_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_ALLOC",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    created = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disposition["order"]["id"],
              "amount": "70.00", "currency": "CNY"},
    )
    assert created.status_code == 200, created.text
    memo_id = created.json()["data"]["id"]
    posted = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text
    ship = await create_shipment(client, logistics_headers)
    receivable = await _direct_cny_receivable(
        db_session,
        sales_order_id=ctx["sales_order_id"],
        customer_id=ctx["customer"].id,
        shipment_id=ship["id"],
        amount="100.00",
    )

    allocated = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/allocations",
        headers=finance_headers,
        json={
            "account_id": receivable.id,
            "amount": "50.00",
            "idempotency_key": f"manual-test-{memo_id}-{receivable.id}",
        },
    )
    assert allocated.status_code == 200, allocated.text
    alloc_id = allocated.json()["data"]["allocation_id"]
    await db_session.refresh(receivable)
    memo = (await db_session.execute(
        select(CustomerCreditMemo).where(CustomerCreditMemo.id == memo_id)
    )).scalar_one()
    assert Decimal(str(receivable.amount_allocated)) == Decimal("50.00")
    assert Decimal(str(receivable.amount_outstanding)) == Decimal("50.00")
    assert Decimal(str(memo.amount_allocated)) == Decimal("50.00")
    assert Decimal(str(memo.amount_unallocated)) == Decimal("20.00")

    detail = await client.get(f"/api/v1/receivables/{receivable.id}", headers=finance_headers)
    assert detail.status_code == 200, detail.text
    alloc_rows = detail.json()["data"]["allocations"]
    assert alloc_rows[0]["source_type"] == "CUSTOMER_CREDIT_MEMO"
    assert alloc_rows[0]["customer_credit_memo_id"] == memo_id

    blocked_void = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/void",
        headers=finance_headers,
        json={"void_reason": "测试作废"},
    )
    assert blocked_void.status_code == 409

    reversed_alloc = await client.post(
        f"/api/v1/customer-credit-memos/allocations/{alloc_id}/reverse",
        headers=finance_headers,
        json={"reverse_reason": "测试反抵扣"},
    )
    assert reversed_alloc.status_code == 200, reversed_alloc.text
    await db_session.refresh(receivable)
    await db_session.refresh(memo)
    assert Decimal(str(receivable.amount_allocated)) == Decimal("0.00")
    assert Decimal(str(memo.amount_allocated)) == Decimal("0.00")
    allocation = (await db_session.execute(
        select(CustomerCreditAllocation).where(CustomerCreditAllocation.id == alloc_id)
    )).scalar_one()
    assert allocation.reversed_at is not None

    voided = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/void",
        headers=finance_headers,
        json={"void_reason": "未使用作废"},
    )
    assert voided.status_code == 200, voided.text
    data = voided.json()["data"]
    assert data["status"] == "VOIDED"
    assert data["posted_at"] is not None
    assert data["posted_by"] is not None


async def test_customer_credit_reject_requires_reason_and_finance_cannot_resubmit(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUCCM_REASON",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    created = await client.post(
        "/api/v1/customer-credit-memos",
        headers=sales_headers,
        json={"inventory_disposition_order_id": disposition["order"]["id"], "amount": "45.00"},
    )
    assert created.status_code == 200, created.text
    memo_id = created.json()["data"]["id"]

    empty_reason = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/reject",
        headers=finance_headers,
        json={"reject_reason": ""},
    )
    assert empty_reason.status_code == 422

    rejected = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/reject",
        headers=finance_headers,
        json={"reject_reason": "缺少客户确认"},
    )
    assert rejected.status_code == 200, rejected.text
    finance_resubmit = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/resubmit",
        headers=finance_headers,
        json={"amount": "45.00"},
    )
    assert finance_resubmit.status_code == 403


async def test_customer_credit_memo_currency_fixed_by_api_and_db_check(
        client, db_session, sales_headers, purchaser_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_qty=10, po_price="5.00", received=10, sku_codes=("SKUCCM_C",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    disposition_id = disposition["order"]["id"]

    api_rejected = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={
            "inventory_disposition_order_id": disposition_id,
            "amount": "10.00",
            "currency": "USD",
        },
    )
    assert api_rejected.status_code == 422

    db_session.add(CustomerCreditMemo(
        no="CCMTESTUSD",
        inventory_disposition_order_id=disposition_id,
        sales_order_id=ctx["sales_order_id"],
        customer_id=ctx["customer"].id,
        currency="USD",
        memo_type=CustomerCreditMemoType.INVENTORY_DISPOSITION,
        status=CustomerCreditMemoStatus.PENDING_APPROVAL,
        amount=Decimal("10.00"),
        amount_allocated=Decimal("0.00"),
        created_by=1,
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
