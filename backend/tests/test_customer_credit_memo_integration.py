from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db.models.ap_credit_memo import APCreditMemo
from app.db.models.customer_credit_memo import (
    CustomerCreditMemo,
    CustomerCreditMemoStatus,
    CustomerCreditMemoType,
)
from app.db.models.payable import Payable
from app.services import customer_credit_memo_service
from tests.outbound_helpers import setup_available_stock

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
        headers=finance_headers,
        json={},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    new_id = resubmitted.json()["data"]["id"]
    assert new_id != first_id
    assert resubmitted.json()["data"]["status"] == "PENDING_APPROVAL"

    duplicate_resubmit = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/resubmit",
        headers=finance_headers,
        json={},
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
