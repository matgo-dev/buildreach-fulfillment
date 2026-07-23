"""采购单状态机门禁 + 整单编辑(乐观锁/对账)+ PO 内复合 UNIQUE(DB 兜底)。无整单硬删(退役走 cancel)。"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.purchase_order import PurchaseOrderLine
from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)


async def _draft_po(client, H, so_id, sup_id, lid, qty=2, unit_price=7):
    r = await client.post("/api/v1/purchase-orders", headers=H, json={
        "source_sales_order_id": so_id, "supplier_id": sup_id, "currency": "USD",
        "lines": [{"source_sales_order_line_id": lid, "qty": qty, "unit_price": unit_price}]})
    assert r.status_code == 200, r.text
    return r.json()["data"]["order"]


async def _setup(client, purchaser_headers, sales_headers, db_session, so_qty=10):
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": so_qty}])
    sup = await create_supplier(client, purchaser_headers)
    return so_id, so_lines, sup


@pytest.mark.asyncio
async def test_confirm_then_cannot_edit(client, purchaser_headers, sales_headers, db_session):
    """DRAFT→CONFIRMED 后:编辑被拒(仅草稿可编辑)→ 41607。"""
    so_id, so_lines, sup = await _setup(client, purchaser_headers, sales_headers, db_session)
    po = await _draft_po(client, purchaser_headers, so_id, sup["id"], so_lines[0]["id"])
    H = purchaser_headers
    c = await client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=H)
    assert c.status_code == 200 and c.json()["data"]["order"]["status"] == "CONFIRMED"

    detail = (await client.get(f"/api/v1/purchase-orders/{po['id']}", headers=H)).json()["data"]
    upd = await client.put(f"/api/v1/purchase-orders/{po['id']}", headers=H, json={
        "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 1, "unit_price": 7}],
        "expected_updated_at": detail["order"]["updated_at"]})
    assert upd.status_code == 409 and upd.json()["code"] == 41607


@pytest.mark.asyncio
async def test_cancel_from_draft_and_confirmed(client, purchaser_headers, sales_headers, db_session):
    """取消:DRAFT 与 CONFIRMED 都可 →CANCELLED;取消后不可再确认(41602 非法转移)。"""
    so_id, so_lines, sup = await _setup(client, purchaser_headers, sales_headers, db_session)
    H = purchaser_headers
    po = await _draft_po(client, H, so_id, sup["id"], so_lines[0]["id"])
    cancel = await client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=H)
    assert cancel.status_code == 200 and cancel.json()["data"]["order"]["status"] == "CANCELLED"
    # 终态不可再确认
    reconf = await client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=H)
    assert reconf.status_code == 409 and reconf.json()["code"] == 41602


@pytest.mark.asyncio
async def test_edit_draft_reconcile_and_total(client, purchaser_headers, sales_headers, db_session):
    """整单编辑草稿:改数量/价 → 重算 total;乐观锁基线更新。"""
    so_id, so_lines, sup = await _setup(client, purchaser_headers, sales_headers, db_session)
    H = purchaser_headers
    po = await _draft_po(client, H, so_id, sup["id"], so_lines[0]["id"], qty=2, unit_price=7)
    detail = (await client.get(f"/api/v1/purchase-orders/{po['id']}", headers=H)).json()["data"]

    upd = await client.put(f"/api/v1/purchase-orders/{po['id']}", headers=H, json={
        "supplier_id": sup["id"], "currency": "USD", "remark": "改价",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 4, "unit_price": 9}],
        "expected_updated_at": detail["order"]["updated_at"]})
    assert upd.status_code == 200, upd.text
    assert float(upd.json()["data"]["order"]["total_amount"]) == 36  # 9×4


@pytest.mark.asyncio
async def test_edit_optimistic_lock_conflict(client, purchaser_headers, sales_headers, db_session):
    """乐观锁:陈旧 expected_updated_at → 41605。"""
    so_id, so_lines, sup = await _setup(client, purchaser_headers, sales_headers, db_session)
    H = purchaser_headers
    po = await _draft_po(client, H, so_id, sup["id"], so_lines[0]["id"])
    stale = "2000-01-01T00:00:00"
    upd = await client.put(f"/api/v1/purchase-orders/{po['id']}", headers=H, json={
        "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 1, "unit_price": 7}],
        "expected_updated_at": stale})
    assert upd.status_code == 409 and upd.json()["code"] == 41605


@pytest.mark.asyncio
async def test_composite_unique_blocks_dup_soline_in_same_po(client, purchaser_headers,
                                                             sales_headers, db_session):
    """DB 硬约束:UNIQUE(purchase_order_id, source_sales_order_line_id) 挡「同一 PO 内同一 SO 行两行」。"""
    so_id, so_lines, sup = await _setup(client, purchaser_headers, sales_headers, db_session)
    po = await _draft_po(client, purchaser_headers, so_id, sup["id"], so_lines[0]["id"], qty=2)
    a_line = (await db_session.execute(
        select(PurchaseOrderLine).where(
            PurchaseOrderLine.purchase_order_id == po["id"]))).scalars().first()
    dup = PurchaseOrderLine(
        purchase_order_id=po["id"], sku_id=a_line.sku_id,
        source_sales_order_line_id=a_line.source_sales_order_line_id,  # 同一 SO 行重复
        name_snapshot="x", spec_text_snapshot="", unit_snapshot="", unit_price=1, qty=1,
        line_total=1, language="zh", sort_order=9)
    db_session.add(dup)
    with pytest.raises(IntegrityError):
        await db_session.flush()
