"""出库前履约中取消申请 MVP-1。

只承载申请和审批事实,不自动回滚正向单据、不自动冲销应付、不自动扣库存。
"""
import pytest
from sqlalchemy import select

from app.db.models.reverse_request import (
    ReverseGoodsStatus,
    ReverseRequest,
    ReverseRequestStatus,
    ReverseRequestType,
)
from app.db.models.user import User

from tests.inbound_helpers import setup_confirmed_po
from tests.outbound_helpers import create_outbound, create_shipment, setup_available_stock

pytestmark = pytest.mark.asyncio


async def _create_inbound(client, headers, po_id: int, po_line_id: int, *, receive: bool = False) -> int:
    cr = await client.post("/api/v1/inbound-orders", headers=headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_line_id, "qty": 3}],
    })
    assert cr.status_code == 200, cr.text
    inbound_id = cr.json()["data"]["order"]["id"]
    if receive:
        rr = await client.post(f"/api/v1/inbound-orders/{inbound_id}/receive",
                               headers=headers, json={})
        assert rr.status_code == 200, rr.text
    return inbound_id


async def test_create_pre_outbound_reverse_request_from_in_transit_inbound(
        client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    inbound_id = await _create_inbound(client, purchaser_headers, po_id, po_lines[0]["id"])

    r = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json={
        "inbound_order_id": inbound_id,
        "reason": "客户取消,供应商已发货但未到仓",
    })
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    req = data["request"]
    assert req["no"].startswith("RR")
    assert req["request_type"] == "FULFILLMENT_CANCEL"
    assert req["status"] == "PENDING_REVIEW"
    assert req["goods_status"] == "IN_TRANSIT"
    assert req["inbound_order_id"] == inbound_id
    assert data["lines"][0]["purchase_order_line_id"] == po_lines[0]["id"]

    listed = await client.get("/api/v1/reverse-requests", headers=purchaser_headers)
    assert listed.status_code == 200, listed.text
    assert any(it["id"] == req["id"] for it in listed.json()["data"]["items"])


async def test_reverse_request_approve_and_complete_received_inbound(
        client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    inbound_id = await _create_inbound(
        client, purchaser_headers, po_id, po_lines[0]["id"], receive=True)
    created = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json={
        "inbound_order_id": inbound_id,
        "reason": "客户取消,供应商同意退回",
    })
    req_id = created.json()["data"]["request"]["id"]
    assert created.json()["data"]["request"]["goods_status"] == "RECEIVED"

    approved = await client.post(
        f"/api/v1/reverse-requests/{req_id}/approve",
        headers=purchaser_headers,
        json={
            "supplier_resolution": "SUPPLIER_ACCEPTS_RETURN",
            "review_note": "供应商同意退回,财务后续冲应付",
        })
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["request"]["status"] == "APPROVED"
    assert approved.json()["data"]["request"]["supplier_resolution"] == "SUPPLIER_ACCEPTS_RETURN"

    completed = await client.post(
        f"/api/v1/reverse-requests/{req_id}/complete",
        headers=purchaser_headers,
        json={"completion_note": "线下退回和财务处理待后续单据承载"})
    assert completed.status_code == 200, completed.text
    assert completed.json()["data"]["request"]["status"] == "COMPLETED"


async def test_reverse_request_reject_marks_original_chain_continue(
        client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    inbound_id = await _create_inbound(client, purchaser_headers, po_id, po_lines[0]["id"])
    created = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json={
        "inbound_order_id": inbound_id,
        "reason": "客户要求取消,供应商不同意",
    })
    req_id = created.json()["data"]["request"]["id"]

    rejected = await client.post(
        f"/api/v1/reverse-requests/{req_id}/reject",
        headers=purchaser_headers,
        json={"review_note": "供应商不接受且公司不承担,原正向链路继续"})
    assert rejected.status_code == 200, rejected.text
    req = rejected.json()["data"]["request"]
    assert req["status"] == "REJECTED"
    assert req["supplier_resolution"] is None


async def test_active_reverse_request_blocks_outbound_creation(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, received=10)
    created = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "reason": "客户取消,先暂停正向出库",
    })
    assert created.status_code == 200, created.text

    ship = await create_shipment(client, logistics_headers)
    r = await create_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"],
        shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 3}])
    assert r.status_code == 409
    assert r.json()["code"] == 41912
    assert r.json()["data"]["reverse_request"]["id"] == created.json()["data"]["request"]["id"]


async def test_rejected_reverse_request_allows_original_chain_continue(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, received=10)
    created = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "reason": "客户取消,供应商不同意",
    })
    assert created.status_code == 200, created.text
    req_id = created.json()["data"]["request"]["id"]
    rejected = await client.post(
        f"/api/v1/reverse-requests/{req_id}/reject",
        headers=purchaser_headers,
        json={"review_note": "供应商不接受且公司不承担,原正向链路继续"})
    assert rejected.status_code == 200, rejected.text

    ship = await create_shipment(client, logistics_headers)
    r = await create_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"],
        shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 3}])
    assert r.status_code == 200, r.text


async def test_active_reverse_request_blocks_existing_draft_outbound_confirmation(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, received=10)
    ship = await create_shipment(client, logistics_headers)
    created = await create_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"],
        shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 3}])
    assert created.status_code == 200, created.text
    outbound_id = created.json()["data"]["order"]["id"]

    requester_id = (await db_session.execute(
        select(User.id).where(User.email == "purchaser@fulfillment.local")
    )).scalar_one()
    db_session.add(ReverseRequest(
        no="RRTESTCONFIRM",
        request_type=ReverseRequestType.FULFILLMENT_CANCEL,
        status=ReverseRequestStatus.PENDING_REVIEW,
        sales_order_id=ctx["sales_order_id"],
        purchase_order_id=ctx["purchase_order_id"],
        inbound_order_id=ctx["inbound_order_id"],
        goods_status=ReverseGoodsStatus.RECEIVED,
        reason="并发或后台补录的逆向申请",
        requested_by=requester_id,
    ))
    await db_session.commit()

    r = await client.post(f"/api/v1/outbound-orders/{outbound_id}/confirm",
                          headers=logistics_headers)
    assert r.status_code == 409
    assert r.json()["code"] == 41912


async def test_reverse_request_blocked_after_outbound_order_exists(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    ctx = await setup_available_stock(
        client, db_session, sales_headers, purchaser_headers, so_qty=10, received=10)
    ship = await create_shipment(client, logistics_headers)
    ob = await create_outbound(
        client, logistics_headers, sales_order_id=ctx["sales_order_id"],
        shipment_id=ship["id"],
        lines=[{"sales_order_line_id": ctx["so_lines"][0]["id"], "qty": 3}])
    assert ob.status_code == 200, ob.text

    r = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json={
        "inbound_order_id": ctx["inbound_order_id"],
        "reason": "已有出库单后不能走出库前取消",
    })
    assert r.status_code == 409
    assert r.json()["code"] == 42303
    assert r.json()["data"]["blocking_documents"][0]["type"] == "outbound_order"


async def test_reverse_request_active_duplicate_blocked(
        client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    inbound_id = await _create_inbound(client, purchaser_headers, po_id, po_lines[0]["id"])
    payload = {"inbound_order_id": inbound_id, "reason": "第一次申请"}
    first = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json=payload)
    assert first.status_code == 200, first.text

    dup = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json={
        "inbound_order_id": inbound_id,
        "reason": "重复申请",
    })
    assert dup.status_code == 409
    assert dup.json()["code"] == 42304


async def test_reverse_request_reason_must_not_be_blank(
        client, db_session, sales_headers, purchaser_headers):
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    inbound_id = await _create_inbound(client, purchaser_headers, po_id, po_lines[0]["id"])

    r = await client.post("/api/v1/reverse-requests", headers=purchaser_headers, json={
        "inbound_order_id": inbound_id,
        "reason": "   ",
    })
    assert r.status_code == 409
    assert r.json()["code"] == 42302
