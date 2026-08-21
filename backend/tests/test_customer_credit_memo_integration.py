import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.audit.constants import AuditAction, AuditResourceType
from app.core.exceptions import (
    AllocationExceedsSourceError,
    AllocationReverseNotFoundError,
    SourceHasActiveAllocationsError,
    SourceVoidedError,
)
from app.db.models.ap_credit_memo import APCreditMemo
from app.db.models.audit_log import AuditLog
from app.db.models.customer import Customer
from app.db.models.customer_credit_memo import (
    CustomerCreditAllocation,
    CustomerCreditMemo,
    CustomerCreditMemoStatus,
    CustomerCreditMemoType,
)
from app.db.models.inbound_order import InboundOrder, InboundOrderStatus
from app.db.models.inventory_disposition import (
    InventoryDispositionOrder,
    InventoryDispositionReceiptHandling,
    InventoryDispositionStatus,
)
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.payable import Payable
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderStatus
from app.db.models.quotation import QuotationOrder, QuotationStatus
from app.db.models.receivable import Receivable
from app.db.models.sales_order import SalesOrder, SalesOrderStatus
from app.db.models.shipment_order import ShipmentOrder, ShipmentOrderStatus
from app.db.models.supplier import Supplier
from app.services import customer_credit_memo_service
from tests.outbound_helpers import (
    create_and_confirm_outbound,
    create_shipment,
    setup_available_stock,
)

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


async def _direct_cancelled_outbound(
    db_session, *, sales_order_id: int, shipment_id: int,
) -> OutboundOrder:
    outbound = OutboundOrder(
        no=f"OBCCMCANCEL{sales_order_id}{shipment_id}",
        sales_order_id=sales_order_id,
        shipment_id=shipment_id,
        status=OutboundOrderStatus.CANCELLED,
        created_by=1,
    )
    db_session.add(outbound)
    await db_session.commit()
    await db_session.refresh(outbound)
    return outbound


async def _seed_direct_posted_credit_graph(
    Session,
    *,
    suffix: str,
    memo_amount: str = "100.00",
    receivable_amount: str = "100.00",
) -> dict[str, int]:
    """Commit a minimal visible graph for true multi-connection concurrency tests."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    code = suffix[:12]
    async with Session() as db:
        customer = Customer(code=f"CC{code}"[:20], name=f"并发客户{suffix}")
        supplier = Supplier(code=f"SC{code}"[:20], name=f"并发供应商{suffix}")
        db.add_all([customer, supplier])
        await db.flush()

        quote = QuotationOrder(
            no=f"QCC{suffix}"[:30],
            customer_id=customer.id,
            salesperson_id=1,
            language="zh",
            currency="CNY",
            status=QuotationStatus.CONVERTED,
            total_amount=Decimal(receivable_amount),
            created_by=1,
        )
        db.add(quote)
        await db.flush()
        sales_order = SalesOrder(
            no=f"SOCC{suffix}"[:30],
            source_quotation_id=quote.id,
            customer_id=customer.id,
            salesperson_id=1,
            language="zh",
            currency="CNY",
            status=SalesOrderStatus.CONFIRMED,
            total_amount=Decimal(receivable_amount),
            created_by=1,
        )
        db.add(sales_order)
        await db.flush()

        purchase_order = PurchaseOrder(
            no=f"POCC{suffix}"[:30],
            source_sales_order_id=sales_order.id,
            supplier_id=supplier.id,
            currency="USD",
            status=PurchaseOrderStatus.CONFIRMED,
            total_amount=Decimal("0.00"),
            created_by=1,
        )
        shipment = ShipmentOrder(
            no=f"SHCC{suffix}"[:30],
            status=ShipmentOrderStatus.OPEN,
            created_by=1,
        )
        db.add_all([purchase_order, shipment])
        await db.flush()

        inbound = InboundOrder(
            no=f"IBCC{suffix}"[:30],
            purchase_order_id=purchase_order.id,
            status=InboundOrderStatus.RECEIVED,
            arrived_at=now.date(),
            created_by=1,
        )
        outbound = OutboundOrder(
            no=f"OBCC{suffix}"[:30],
            sales_order_id=sales_order.id,
            shipment_id=shipment.id,
            status=OutboundOrderStatus.ISSUED,
            issued_at=now,
            created_by=1,
        )
        db.add_all([inbound, outbound])
        await db.flush()

        payable = Payable(
            inbound_order_id=inbound.id,
            purchase_order_id=purchase_order.id,
            supplier_id=supplier.id,
            currency="USD",
            amount_original=Decimal("0.00"),
            amount_allocated=Decimal("0.00"),
            amount_credited=Decimal("0.00"),
            created_by=1,
        )
        receivable = Receivable(
            outbound_order_id=outbound.id,
            sales_order_id=sales_order.id,
            customer_id=customer.id,
            currency="CNY",
            amount_original=Decimal(receivable_amount),
            amount_allocated=Decimal("0.00"),
            created_by=1,
        )
        db.add_all([payable, receivable])
        await db.flush()

        disposition = InventoryDispositionOrder(
            no=f"IDCC{suffix}"[:30],
            inbound_order_id=inbound.id,
            purchase_order_id=purchase_order.id,
            sales_order_id=sales_order.id,
            payable_id=payable.id,
            purchase_currency="USD",
            status=InventoryDispositionStatus.HELD,
            receipt_handling=InventoryDispositionReceiptHandling.RECEIVE_TO_DISPOSITION,
            supplier_payable_amount=Decimal("0.00"),
            created_by=1,
            held_at=now,
            held_by=1,
        )
        db.add(disposition)
        await db.flush()

        memo = CustomerCreditMemo(
            no=f"CCM{suffix}"[:30],
            inventory_disposition_order_id=disposition.id,
            sales_order_id=sales_order.id,
            customer_id=customer.id,
            currency="CNY",
            memo_type=CustomerCreditMemoType.INVENTORY_DISPOSITION,
            status=CustomerCreditMemoStatus.POSTED,
            amount=Decimal(memo_amount),
            amount_allocated=Decimal("0.00"),
            amount_basis="并发测试人民币金额依据",
            posted_at=now,
            posted_by=1,
            created_by=1,
        )
        db.add(memo)
        await db.commit()
        return {
            "customer_id": customer.id,
            "supplier_id": supplier.id,
            "quotation_id": quote.id,
            "sales_order_id": sales_order.id,
            "purchase_order_id": purchase_order.id,
            "shipment_id": shipment.id,
            "inbound_id": inbound.id,
            "outbound_id": outbound.id,
            "payable_id": payable.id,
            "receivable_id": receivable.id,
            "disposition_id": disposition.id,
            "memo_id": memo.id,
        }


async def _cleanup_direct_credit_graph(Session, ids: dict[str, int]) -> None:
    async with Session() as db:
        await db.execute(delete(AuditLog).where(
            AuditLog.resource_type == AuditResourceType.CUSTOMER_CREDIT_MEMO,
            AuditLog.resource_id == str(ids["memo_id"]),
        ))
        await db.execute(delete(CustomerCreditAllocation).where(
            CustomerCreditAllocation.customer_credit_memo_id == ids["memo_id"]))
        for model, key in [
            (CustomerCreditMemo, "memo_id"),
            (Receivable, "receivable_id"),
            (InventoryDispositionOrder, "disposition_id"),
            (Payable, "payable_id"),
            (OutboundOrder, "outbound_id"),
            (InboundOrder, "inbound_id"),
            (PurchaseOrder, "purchase_order_id"),
            (ShipmentOrder, "shipment_id"),
            (SalesOrder, "sales_order_id"),
            (QuotationOrder, "quotation_id"),
            (Supplier, "supplier_id"),
            (Customer, "customer_id"),
        ]:
            await db.execute(delete(model).where(model.id == ids[key]))
        await db.commit()


async def _manual_allocate_in_new_session(
    Session,
    ids: dict[str, int],
    *,
    amount: str,
    key: str,
):
    async with Session() as db:
        return await customer_credit_memo_service.manual_allocate(
            db,
            memo_id=ids["memo_id"],
            receivable_id=ids["receivable_id"],
            amount=Decimal(amount),
            idempotency_key=key,
            actor_user_id=1,
            actor_user_email="finance@test",
        )


async def test_customer_credit_memo_posts_cny_balance_without_touching_supplier_ap(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, unit_price="20.00", po_price="5.00", received=10,
        sku_codes=("SKUCCM_A",))
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
            "amount_basis": "线下审批单 OA-CCM-001 确认人民币补偿 123.45",
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
    assert posted_memo["amount_basis"] == "线下审批单 OA-CCM-001 确认人民币补偿 123.45"
    create_audit = (await db_session.execute(
        select(AuditLog)
        .where(
            AuditLog.resource_type == AuditResourceType.CUSTOMER_CREDIT_MEMO,
            AuditLog.action == AuditAction.CREATE,
            AuditLog.resource_id == str(memo["id"]),
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    )).scalar_one()
    assert create_audit.extra["amount_basis"] == "线下审批单 OA-CCM-001 确认人民币补偿 123.45"

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
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_B",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    disposition_id = disposition["order"]["id"]

    first = await client.post(
        "/api/v1/customer-credit-memos",
        headers=sales_headers,
        json={"inventory_disposition_order_id": disposition_id, "amount": "88.00",
              "amount_basis": "首次人民币补偿依据"},
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["data"]["id"]

    duplicate = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disposition_id, "amount": "88.00",
              "amount_basis": "重复提交依据"},
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
        json={"amount": "66.00", "amount_basis": "补充线下审批单后人民币补偿 66",
              "reason": "补充材料后重提"},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    new_id = resubmitted.json()["data"]["id"]
    assert new_id != first_id
    assert resubmitted.json()["data"]["status"] == "PENDING_APPROVAL"
    assert resubmitted.json()["data"]["resubmitted_from_id"] == first_id
    assert Decimal(str(resubmitted.json()["data"]["amount"])) == Decimal("66.00")
    assert resubmitted.json()["data"]["amount_basis"] == "补充线下审批单后人民币补偿 66"

    duplicate_resubmit = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/resubmit",
        headers=sales_headers,
        json={"amount": "66.00", "amount_basis": "重复重提依据"},
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


async def test_customer_credit_memo_manual_cny_basis_allows_foreign_source_sales_order(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="USD", so_qty=10, unit_price="10.00", po_price="5.00", received=10,
        sku_codes=("SKUCCM_FX_MANUAL",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    created = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disposition["order"]["id"],
              "amount": "500.00", "currency": "CNY",
              "amount_basis": "销售为 USD,财务按线下审批确认人民币补偿 500"},
    )
    assert created.status_code == 200, created.text
    memo = created.json()["data"]
    assert memo["currency"] == "CNY"
    assert memo["amount_basis"] == "销售为 USD,财务按线下审批确认人民币补偿 500"

    posted = await client.post(
        f"/api/v1/customer-credit-memos/{memo['id']}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text
    assert posted.json()["data"]["status"] == "POSTED"


async def test_customer_credit_memo_amount_basis_required_on_create_and_resubmit(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    create_ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, unit_price="10.00", po_price="5.00", received=10,
        sku_codes=("SKUCCM_BASIS_CREATE",))
    create_disposition = await _create_held_disposition(
        client, purchaser_headers, create_ctx["inbound_order_id"])
    missing_create = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": create_disposition["order"]["id"],
              "amount": "10.00", "currency": "CNY"},
    )
    assert missing_create.status_code == 422
    blank_create = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": create_disposition["order"]["id"],
              "amount": "10.00", "currency": "CNY", "amount_basis": " "},
    )
    assert blank_create.status_code == 422

    resubmit_ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, unit_price="10.00", po_price="5.00", received=10,
        sku_codes=("SKUCCM_BASIS_RESUBMIT",))
    resubmit_disposition = await _create_held_disposition(
        client, purchaser_headers, resubmit_ctx["inbound_order_id"])
    first = await client.post(
        "/api/v1/customer-credit-memos",
        headers=sales_headers,
        json={"inventory_disposition_order_id": resubmit_disposition["order"]["id"],
              "amount": "80.00", "currency": "CNY", "amount_basis": "初始审批依据"},
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["data"]["id"]
    rejected = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/reject",
        headers=finance_headers,
        json={"reject_reason": "需要重提"},
    )
    assert rejected.status_code == 200, rejected.text

    missing_resubmit = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/resubmit",
        headers=sales_headers,
        json={"amount": "80.00", "reason": "缺少依据"},
    )
    assert missing_resubmit.status_code == 422


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
              "amount": "70.00", "currency": "CNY", "amount_basis": "抵扣测试人民币依据"},
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
    allocated_again = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/allocations",
        headers=finance_headers,
        json={
            "account_id": receivable.id,
            "amount": "20.00",
            "idempotency_key": f"manual-test-2-{memo_id}-{receivable.id}",
        },
    )
    assert allocated_again.status_code == 200, allocated_again.text
    await db_session.refresh(receivable)
    memo = (await db_session.execute(
        select(CustomerCreditMemo).where(CustomerCreditMemo.id == memo_id)
    )).scalar_one()
    assert Decimal(str(receivable.amount_allocated)) == Decimal("70.00")
    assert Decimal(str(receivable.amount_outstanding)) == Decimal("30.00")
    assert Decimal(str(memo.amount_allocated)) == Decimal("70.00")
    assert Decimal(str(memo.amount_unallocated)) == Decimal("0.00")

    detail = await client.get(f"/api/v1/receivables/{receivable.id}", headers=finance_headers)
    assert detail.status_code == 200, detail.text
    alloc_rows = detail.json()["data"]["allocations"]
    assert alloc_rows[0]["source_type"] == "CUSTOMER_CREDIT_MEMO"
    assert alloc_rows[0]["customer_credit_memo_id"] == memo_id
    assert len([row for row in alloc_rows if row["source_type"] == "CUSTOMER_CREDIT_MEMO"]) == 2

    blocked_void = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/void",
        headers=finance_headers,
        json={"void_reason": "测试作废"},
    )
    assert blocked_void.status_code == 409

    empty_reverse = await client.post(
        f"/api/v1/customer-credit-memos/allocations/{alloc_id}/reverse",
        headers=finance_headers,
        json={"reverse_reason": "   ", "idempotency_key": f"reverse-empty-{alloc_id}"},
    )
    assert empty_reverse.status_code == 422

    reverse_key = f"reverse-{alloc_id}"
    reversed_alloc = await client.post(
        f"/api/v1/customer-credit-memos/allocations/{alloc_id}/reverse",
        headers=finance_headers,
        json={"reverse_reason": "测试反抵扣", "idempotency_key": reverse_key},
    )
    assert reversed_alloc.status_code == 200, reversed_alloc.text
    reverse_replay = await client.post(
        f"/api/v1/customer-credit-memos/allocations/{alloc_id}/reverse",
        headers=finance_headers,
        json={"reverse_reason": "测试反抵扣", "idempotency_key": reverse_key},
    )
    assert reverse_replay.status_code == 200, reverse_replay.text
    reverse_conflict = await client.post(
        f"/api/v1/customer-credit-memos/allocations/{alloc_id}/reverse",
        headers=finance_headers,
        json={"reverse_reason": "不同原因", "idempotency_key": reverse_key},
    )
    assert reverse_conflict.status_code == 409
    assert reverse_conflict.json()["code"] == 42211
    reverse_other_key = await client.post(
        f"/api/v1/customer-credit-memos/allocations/{alloc_id}/reverse",
        headers=finance_headers,
        json={"reverse_reason": "测试反抵扣", "idempotency_key": f"reverse-other-{alloc_id}"},
    )
    assert reverse_other_key.status_code == 404
    await db_session.refresh(receivable)
    await db_session.refresh(memo)
    assert Decimal(str(receivable.amount_allocated)) == Decimal("20.00")
    assert Decimal(str(memo.amount_allocated)) == Decimal("20.00")
    allocation = (await db_session.execute(
        select(CustomerCreditAllocation).where(CustomerCreditAllocation.id == alloc_id)
    )).scalar_one()
    assert allocation.reversed_at is not None

    memo_detail = await client.get(f"/api/v1/customer-credit-memos/{memo_id}",
                                   headers=finance_headers)
    assert memo_detail.status_code == 200, memo_detail.text
    history = memo_detail.json()["data"]["allocations"]
    reversed_rows = [row for row in history if row["id"] == alloc_id]
    assert reversed_rows and reversed_rows[0]["status"] == "REVERSED"
    assert reversed_rows[0]["reverse_reason"] == "测试反抵扣"
    receivable_detail = await client.get(f"/api/v1/receivables/{receivable.id}",
                                         headers=finance_headers)
    assert any(row["id"] == alloc_id and row["status"] == "REVERSED"
               for row in receivable_detail.json()["data"]["allocations"])

    second_alloc_id = allocated_again.json()["data"]["allocation_id"]
    second_reverse = await client.post(
        f"/api/v1/customer-credit-memos/allocations/{second_alloc_id}/reverse",
        headers=finance_headers,
        json={"reverse_reason": "清空剩余抵扣",
              "idempotency_key": f"reverse-{second_alloc_id}"},
    )
    assert second_reverse.status_code == 200, second_reverse.text
    empty_void = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/void",
        headers=finance_headers,
        json={"void_reason": " "},
    )
    assert empty_void.status_code == 422

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


async def test_customer_credit_allocation_idempotency_is_bound_to_request(
        client, db_session, sales_headers, purchaser_headers, finance_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_IDP",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    created = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disposition["order"]["id"],
              "amount": "90.00", "currency": "CNY", "amount_basis": "幂等测试人民币依据"},
    )
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

    key = f"idp-bound-{memo_id}-{receivable.id}"
    first = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/allocations",
        headers=finance_headers,
        json={"account_id": receivable.id, "amount": "30.00", "idempotency_key": key},
    )
    assert first.status_code == 200, first.text
    first_id = first.json()["data"]["allocation_id"]
    replay = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/allocations",
        headers=finance_headers,
        json={"account_id": receivable.id, "amount": "30.00", "idempotency_key": key},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["data"]["allocation_id"] == first_id

    mismatched_amount = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/allocations",
        headers=finance_headers,
        json={"account_id": receivable.id, "amount": "20.00", "idempotency_key": key},
    )
    assert mismatched_amount.status_code == 409
    assert mismatched_amount.json()["code"] == 42211
    ship2 = await create_shipment(client, logistics_headers)
    receivable2 = await _direct_cny_receivable(
        db_session,
        sales_order_id=ctx["sales_order_id"],
        customer_id=ctx["customer"].id,
        shipment_id=ship2["id"],
        amount="100.00",
    )
    mismatched_account = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/allocations",
        headers=finance_headers,
        json={"account_id": receivable2.id, "amount": "30.00", "idempotency_key": key},
    )
    assert mismatched_account.status_code == 409
    assert mismatched_account.json()["code"] == 42211


async def test_customer_credit_eligible_receivables_are_memo_scoped_and_paginated(
        client, db_session, sales_headers, purchaser_headers, finance_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, unit_price="30.00", po_price="5.00", received=10,
        sku_codes=("SKUCCM_ELIGIBLE",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    created = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disposition["order"]["id"],
              "amount": "300.00", "currency": "CNY", "amount_basis": "应收筛选测试人民币依据"},
    )
    memo_id = created.json()["data"]["id"]
    posted = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text

    receivables = []
    for idx in range(3):
        ship = await create_shipment(client, logistics_headers)
        receivables.append(await _direct_cny_receivable(
            db_session,
            sales_order_id=ctx["sales_order_id"],
            customer_id=ctx["customer"].id,
            shipment_id=ship["id"],
            amount="100.00",
        ))

    other_ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_ELIGIBLE_OTHER",))
    other_ship = await create_shipment(client, logistics_headers)
    other_receivable = await _direct_cny_receivable(
        db_session,
        sales_order_id=other_ctx["sales_order_id"],
        customer_id=other_ctx["customer"].id,
        shipment_id=other_ship["id"],
        amount="100.00",
    )

    first_page = await client.get(
        f"/api/v1/customer-credit-memos/{memo_id}/eligible-receivables",
        headers=finance_headers,
        params={"page": 1, "size": 2},
    )
    assert first_page.status_code == 200, first_page.text
    data = first_page.json()["data"]
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert [item["id"] for item in data["items"]] == [r.id for r in receivables[:2]]

    second_page = await client.get(
        f"/api/v1/customer-credit-memos/{memo_id}/eligible-receivables",
        headers=finance_headers,
        params={"page": 2, "size": 2},
    )
    assert second_page.status_code == 200, second_page.text
    assert [item["id"] for item in second_page.json()["data"]["items"]] == [receivables[2].id]

    target_outbound_no = (await db_session.execute(
        select(OutboundOrder.no).where(
            OutboundOrder.id == receivables[1].outbound_order_id)
    )).scalar_one()
    searched = await client.get(
        f"/api/v1/customer-credit-memos/{memo_id}/eligible-receivables",
        headers=finance_headers,
        params={"q": target_outbound_no, "page": 1, "size": 20},
    )
    assert searched.status_code == 200, searched.text
    searched_ids = [item["id"] for item in searched.json()["data"]["items"]]
    assert receivables[1].id in searched_ids
    assert other_receivable.id not in searched_ids


async def test_customer_credit_same_idempotency_key_concurrent_replay_is_single_allocation(
        _engine):
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    ids = await _seed_direct_posted_credit_graph(
        Session, suffix="IDPCONC", memo_amount="100.00", receivable_amount="100.00")
    key = f"idp-concurrent-{ids['memo_id']}-{ids['receivable_id']}"
    try:
        results = await asyncio.gather(
            _manual_allocate_in_new_session(Session, ids, amount="40.00", key=key),
            _manual_allocate_in_new_session(Session, ids, amount="40.00", key=key),
        )
        assert results[0].id == results[1].id
        async with Session() as db:
            allocations = (await db.execute(
                select(CustomerCreditAllocation).where(
                    CustomerCreditAllocation.idempotency_key == key)
            )).scalars().all()
            memo = await db.get(CustomerCreditMemo, ids["memo_id"])
            receivable = await db.get(Receivable, ids["receivable_id"])
        assert len(allocations) == 1
        assert Decimal(str(memo.amount_allocated)) == Decimal("40.00")
        assert Decimal(str(receivable.amount_allocated)) == Decimal("40.00")
    finally:
        await _cleanup_direct_credit_graph(Session, ids)


async def test_customer_credit_concurrent_allocations_do_not_overconsume_balance(_engine):
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    ids = await _seed_direct_posted_credit_graph(
        Session, suffix="RACEALLOC", memo_amount="100.00", receivable_amount="100.00")
    try:
        results = await asyncio.gather(
            _manual_allocate_in_new_session(
                Session, ids, amount="70.00",
                key=f"race-a-{ids['memo_id']}-{ids['receivable_id']}"),
            _manual_allocate_in_new_session(
                Session, ids, amount="70.00",
                key=f"race-b-{ids['memo_id']}-{ids['receivable_id']}"),
            return_exceptions=True,
        )
        assert sum(isinstance(r, CustomerCreditAllocation) for r in results) == 1
        assert sum(isinstance(r, AllocationExceedsSourceError) for r in results) == 1
        async with Session() as db:
            memo = await db.get(CustomerCreditMemo, ids["memo_id"])
            receivable = await db.get(Receivable, ids["receivable_id"])
            allocations = (await db.execute(
                select(CustomerCreditAllocation).where(
                    CustomerCreditAllocation.customer_credit_memo_id == ids["memo_id"],
                    CustomerCreditAllocation.reversed_at.is_(None),
                )
            )).scalars().all()
        assert len(allocations) == 1
        assert Decimal(str(receivable.amount_allocated)) == Decimal("70.00")
        assert Decimal(str(memo.amount_allocated)) == Decimal("70.00")
    finally:
        await _cleanup_direct_credit_graph(Session, ids)


async def test_customer_credit_allocate_and_void_concurrency_keeps_single_outcome(_engine):
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    ids = await _seed_direct_posted_credit_graph(
        Session, suffix="RACEVOID", memo_amount="100.00", receivable_amount="100.00")

    async def void_in_new_session():
        async with Session() as db:
            return await customer_credit_memo_service.void_memo(
                db,
                memo_id=ids["memo_id"],
                void_reason="并发作废",
                actor_user_id=1,
                actor_user_email="finance@test",
            )

    try:
        results = await asyncio.gather(
            _manual_allocate_in_new_session(
                Session, ids, amount="60.00",
                key=f"void-race-{ids['memo_id']}-{ids['receivable_id']}"),
            void_in_new_session(),
            return_exceptions=True,
        )
        alloc_won = any(isinstance(r, CustomerCreditAllocation) for r in results)
        void_won = any(isinstance(r, CustomerCreditMemo) for r in results)
        assert alloc_won != void_won
        if alloc_won:
            assert any(isinstance(r, SourceHasActiveAllocationsError) for r in results)
        else:
            assert any(isinstance(r, SourceVoidedError) for r in results)
    finally:
        await _cleanup_direct_credit_graph(Session, ids)


async def test_customer_credit_concurrent_reverse_allocation_is_idempotently_blocked(_engine):
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    ids = await _seed_direct_posted_credit_graph(
        Session, suffix="RACEREV", memo_amount="100.00", receivable_amount="100.00")
    try:
        allocation = await _manual_allocate_in_new_session(
            Session, ids, amount="50.00",
            key=f"reverse-seed-{ids['memo_id']}-{ids['receivable_id']}")

        async def reverse_in_new_session():
            async with Session() as db:
                return await customer_credit_memo_service.reverse_allocation(
                    db,
                    allocation_id=allocation.id,
                    reverse_reason="并发反抵扣",
                    idempotency_key=f"reverse-concurrent-{allocation.id}",
                    actor_user_id=1,
                    actor_user_email="finance@test",
                )

        results = await asyncio.gather(
            reverse_in_new_session(),
            reverse_in_new_session(),
            return_exceptions=True,
        )
        assert sum(isinstance(r, CustomerCreditAllocation) for r in results) == 2
        assert results[0].id == results[1].id
        async with Session() as db:
            memo = await db.get(CustomerCreditMemo, ids["memo_id"])
            receivable = await db.get(Receivable, ids["receivable_id"])
            refreshed_alloc = await db.get(CustomerCreditAllocation, allocation.id)
        assert refreshed_alloc.reversed_at is not None
        assert Decimal(str(memo.amount_allocated)) == Decimal("0.00")
        assert Decimal(str(receivable.amount_allocated)) == Decimal("0.00")
    finally:
        await _cleanup_direct_credit_graph(Session, ids)


async def test_customer_credit_reverse_with_different_key_after_success_is_rejected(_engine):
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    ids = await _seed_direct_posted_credit_graph(
        Session, suffix="REVOTHER", memo_amount="100.00", receivable_amount="100.00")
    try:
        allocation = await _manual_allocate_in_new_session(
            Session, ids, amount="50.00",
            key=f"reverse-other-seed-{ids['memo_id']}-{ids['receivable_id']}")
        async with Session() as db:
            first = await customer_credit_memo_service.reverse_allocation(
                db,
                allocation_id=allocation.id,
                reverse_reason="首次反抵扣",
                idempotency_key=f"reverse-first-{allocation.id}",
                actor_user_id=1,
                actor_user_email="finance@test",
            )
        async with Session() as db:
            replay = await customer_credit_memo_service.reverse_allocation(
                db,
                allocation_id=allocation.id,
                reverse_reason="首次反抵扣",
                idempotency_key=f"reverse-first-{allocation.id}",
                actor_user_id=1,
                actor_user_email="finance@test",
            )
        assert first.id == replay.id
        async with Session() as db:
            with pytest.raises(AllocationReverseNotFoundError):
                await customer_credit_memo_service.reverse_allocation(
                    db,
                    allocation_id=allocation.id,
                    reverse_reason="首次反抵扣",
                    idempotency_key=f"reverse-second-{allocation.id}",
                    actor_user_id=1,
                    actor_user_email="finance@test",
                )
    finally:
        await _cleanup_direct_credit_graph(Session, ids)


async def test_customer_credit_post_and_resubmit_recheck_no_active_outbound(
        client, db_session, sales_headers, purchaser_headers, finance_headers, logistics_headers):
    post_ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_POST_OB",))
    post_disposition = await _create_held_disposition(
        client, purchaser_headers, post_ctx["inbound_order_id"])
    pending = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": post_disposition["order"]["id"],
              "amount": "30.00", "currency": "CNY", "amount_basis": "过账重检测试依据"},
    )
    assert pending.status_code == 200, pending.text
    post_memo_id = pending.json()["data"]["id"]
    ship = await create_shipment(client, logistics_headers)
    await _direct_cny_receivable(
        db_session,
        sales_order_id=post_ctx["sales_order_id"],
        customer_id=post_ctx["customer"].id,
        shipment_id=ship["id"],
        amount="10.00",
    )
    blocked_post = await client.post(
        f"/api/v1/customer-credit-memos/{post_memo_id}/post",
        headers=finance_headers,
        json={},
    )
    assert blocked_post.status_code == 409

    resubmit_ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_RESUB_OB",))
    resubmit_disposition = await _create_held_disposition(
        client, purchaser_headers, resubmit_ctx["inbound_order_id"])
    first = await client.post(
        "/api/v1/customer-credit-memos",
        headers=sales_headers,
        json={"inventory_disposition_order_id": resubmit_disposition["order"]["id"],
              "amount": "30.00", "currency": "CNY", "amount_basis": "重提重检测试依据"},
    )
    first_id = first.json()["data"]["id"]
    rejected = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/reject",
        headers=finance_headers,
        json={"reject_reason": "先驳回"},
    )
    assert rejected.status_code == 200, rejected.text
    ship2 = await create_shipment(client, logistics_headers)
    await _direct_cny_receivable(
        db_session,
        sales_order_id=resubmit_ctx["sales_order_id"],
        customer_id=resubmit_ctx["customer"].id,
        shipment_id=ship2["id"],
        amount="10.00",
    )
    blocked_resubmit = await client.post(
        f"/api/v1/customer-credit-memos/{first_id}/resubmit",
        headers=sales_headers,
        json={"amount": "30.00", "amount_basis": "出库阻断重提依据"},
    )
    assert blocked_resubmit.status_code == 409


async def test_customer_credit_cancelled_outbound_does_not_block_post(
        client, db_session, sales_headers, purchaser_headers, finance_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_CANCELLED_OB",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    created = await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disposition["order"]["id"],
              "amount": "30.00", "currency": "CNY", "amount_basis": "取消出库不阻断测试依据"},
    )
    memo_id = created.json()["data"]["id"]
    ship = await create_shipment(client, logistics_headers)
    await _direct_cancelled_outbound(
        db_session, sales_order_id=ctx["sales_order_id"], shipment_id=ship["id"])
    posted = await client.post(
        f"/api/v1/customer-credit-memos/{memo_id}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text


async def test_customer_credit_auto_allocate_fifo_and_audit_on_outbound(
        client, db_session, sales_headers, purchaser_headers, finance_headers, logistics_headers):
    source_a = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_FIFO_A",))
    disp_a = await _create_held_disposition(
        client, purchaser_headers, source_a["inbound_order_id"])
    memo_a = (await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disp_a["order"]["id"],
              "amount": "30.00", "currency": "CNY", "amount_basis": "FIFO 第一笔人民币依据"},
    )).json()["data"]
    posted_a = await client.post(
        f"/api/v1/customer-credit-memos/{memo_a['id']}/post",
        headers=finance_headers,
        json={},
    )
    assert posted_a.status_code == 200, posted_a.text

    source_b = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_FIFO_B",), customer=source_a["customer"])
    disp_b = await _create_held_disposition(
        client, purchaser_headers, source_b["inbound_order_id"])
    memo_b = (await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disp_b["order"]["id"],
              "amount": "80.00", "currency": "CNY", "amount_basis": "FIFO 第二笔人民币依据"},
    )).json()["data"]
    posted_b = await client.post(
        f"/api/v1/customer-credit-memos/{memo_b['id']}/post",
        headers=finance_headers,
        json={},
    )
    assert posted_b.status_code == 200, posted_b.text

    outbound_ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, unit_price="10.00", po_price="5.00", received=10,
        sku_codes=("SKUCCM_FIFO_OB",), customer=source_a["customer"])
    ship = await create_shipment(client, logistics_headers)
    outbound_id, confirmed = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=outbound_ctx["sales_order_id"],
        shipment_id=ship["id"],
        lines=[{"sales_order_line_id": outbound_ctx["so_lines"][0]["id"], "qty": 10}])
    assert confirmed.status_code == 200, confirmed.text

    receivable = (await db_session.execute(
        select(Receivable).where(Receivable.outbound_order_id == outbound_id)
    )).scalar_one()
    assert Decimal(str(receivable.amount_allocated)) == Decimal("100.00")
    allocs = (await db_session.execute(
        select(CustomerCreditAllocation)
        .where(CustomerCreditAllocation.receivable_id == receivable.id)
        .order_by(CustomerCreditAllocation.id)
    )).scalars().all()
    assert [(a.customer_credit_memo_id, Decimal(str(a.amount))) for a in allocs] == [
        (memo_a["id"], Decimal("30.00")),
        (memo_b["id"], Decimal("70.00")),
    ]
    audit = (await db_session.execute(
        select(AuditLog)
        .where(
            AuditLog.resource_type == AuditResourceType.OUTBOUND_ORDER,
            AuditLog.action == AuditAction.ISSUE,
            AuditLog.resource_id == str(outbound_id),
        )
        .order_by(AuditLog.id.desc())
        .limit(1)
    )).scalar_one()
    assert audit.extra["customer_credit_allocations"] == [
        {"allocation_id": allocs[0].id, "customer_credit_memo_id": memo_a["id"],
         "amount": "30.00"},
        {"allocation_id": allocs[1].id, "customer_credit_memo_id": memo_b["id"],
         "amount": "70.00"},
    ]


async def test_customer_credit_auto_allocate_one_memo_across_multiple_receivables(
        client, db_session, sales_headers, purchaser_headers, finance_headers, logistics_headers):
    source = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, unit_price="12.00", po_price="5.00", received=10,
        sku_codes=("SKUCCM_MULTI_SRC",))
    disp = await _create_held_disposition(client, purchaser_headers, source["inbound_order_id"])
    memo = (await client.post(
        "/api/v1/customer-credit-memos",
        headers=purchaser_headers,
        json={"inventory_disposition_order_id": disp["order"]["id"],
              "amount": "120.00", "currency": "CNY", "amount_basis": "跨多应收自动抵扣测试依据"},
    )).json()["data"]
    posted = await client.post(
        f"/api/v1/customer-credit-memos/{memo['id']}/post",
        headers=finance_headers,
        json={},
    )
    assert posted.status_code == 200, posted.text

    amounts = []
    for idx, qty in enumerate([5, 4], start=1):
        ctx = await setup_available_stock(
            client, db_session, sales_headers, purchaser_headers,
            so_currency="CNY", so_qty=10, unit_price="10.00", po_price="5.00", received=10,
            sku_codes=(f"SKUCCM_MULTI_OB_{idx}",), customer=source["customer"])
        ship = await create_shipment(client, logistics_headers)
        ob_id, confirmed = await create_and_confirm_outbound(
            client, logistics_headers, sales_order_id=ctx["sales_order_id"],
            shipment_id=ship["id"],
            lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": qty}])
        assert confirmed.status_code == 200, confirmed.text
        receivable = (await db_session.execute(
            select(Receivable).where(Receivable.outbound_order_id == ob_id)
        )).scalar_one()
        amounts.append(Decimal(str(receivable.amount_allocated)))

    assert amounts == [Decimal("50.00"), Decimal("40.00")]
    refreshed = (await db_session.execute(
        select(CustomerCreditMemo).where(CustomerCreditMemo.id == memo["id"])
    )).scalar_one()
    assert Decimal(str(refreshed.amount_allocated)) == Decimal("90.00")
    assert Decimal(str(refreshed.amount_unallocated)) == Decimal("30.00")


async def test_customer_credit_reject_requires_reason_and_finance_cannot_resubmit(
        client, db_session, sales_headers, purchaser_headers, finance_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers,
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_REASON",))
    disposition = await _create_held_disposition(
        client, purchaser_headers, ctx["inbound_order_id"])
    created = await client.post(
        "/api/v1/customer-credit-memos",
        headers=sales_headers,
        json={"inventory_disposition_order_id": disposition["order"]["id"], "amount": "45.00",
              "amount_basis": "驳回权限测试人民币依据"},
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
        so_currency="CNY", so_qty=10, po_price="5.00", received=10,
        sku_codes=("SKUCCM_C",))
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
        amount_basis="DB 约束测试人民币依据",
        created_by=1,
    ))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
