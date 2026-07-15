"""采购单建单核心:基于 SO 建 PO(平移快照/金额精度)+ 超采守卫 + PO 内重复挡。

主流程第3步「按单采购」。SKU 范围与数量上限被 SO 约束,SO 自身状态不变。
"""
import pytest

from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)


@pytest.mark.asyncio
async def test_create_po_from_sales_order(client, purchaser_headers, sales_headers, db_session):
    """核心:基于 CONFIRMED SO 建一张 DRAFT PO,平移行快照,总额=Σ行额。"""
    cust, sku = await seed_catalog_and_customer(db_session, reference_price=8)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)

    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 3, "unit_price": 7.5}]})
    assert r.status_code == 200, r.text
    po = r.json()["data"]["order"]
    lines = r.json()["data"]["lines"]
    assert po["no"].startswith("PO")
    assert po["status"] == "DRAFT"
    assert po["source_sales_order_id"] == so_id
    assert po["supplier_id"] == sup["id"]
    assert len(lines) == 1
    # 快照平移自 SO 行(name/spec/unit/sku),采购价全新录入(≠SO 售价 100)。
    assert lines[0]["name_snapshot"] == so_lines[0]["name_snapshot"]
    assert lines[0]["unit_snapshot"] == so_lines[0]["unit_snapshot"]
    assert lines[0]["sku_id"] == so_lines[0]["sku_id"]
    assert float(lines[0]["unit_price"]) == 7.5
    assert float(lines[0]["qty"]) == 3
    assert float(lines[0]["line_total"]) == 22.5   # 7.5 × 3
    assert float(po["total_amount"]) == 22.5


@pytest.mark.asyncio
async def test_line_total_precision(client, purchaser_headers, sales_headers, db_session):
    """金额精度:line_total = unit_price × qty 走 Decimal,不引浮点误差。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 100}])
    sup = await create_supplier(client, purchaser_headers)

    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 3, "unit_price": 0.1}]})
    assert r.status_code == 200, r.text
    # 0.1 × 3 = 0.30(浮点 0.30000000000000004 会破),四舍二位存 0.30。
    assert float(r.json()["data"]["lines"][0]["line_total"]) == 0.3
    assert float(r.json()["data"]["order"]["total_amount"]) == 0.3


@pytest.mark.asyncio
async def test_over_purchase_blocked_single_line(client, purchaser_headers, sales_headers, db_session):
    """超采守卫:单行采购量 > SO 行数量 → 41603。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)

    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 6, "unit_price": 7}]})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == 41603


@pytest.mark.asyncio
async def test_over_purchase_blocked_across_pos(client, purchaser_headers, sales_headers, db_session):
    """跨 PO 累计超采:SO 行 qty=5,先下 3(草稿),再下 3 → 累计 6 > 5 → 41603。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    body = lambda q: {
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": q, "unit_price": 7}]}

    first = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json=body(3))
    assert first.status_code == 200, first.text
    second = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json=body(3))
    assert second.status_code == 409 and second.json()["code"] == 41603


@pytest.mark.asyncio
async def test_draft_counts_toward_quota(client, purchaser_headers, sales_headers, db_session):
    """草稿占额:两张草稿不能重复覆盖同一 SO 行(含 DRAFT 口径)——上一条已验;
    此条验剩余额度恰好可下(qty=5 下 3 再下 2 = 5,不超)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    body = lambda q: {
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": q, "unit_price": 7}]}

    assert (await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json=body(3))).status_code == 200
    assert (await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json=body(2))).status_code == 200


@pytest.mark.asyncio
async def test_empty_po_rejected(client, purchaser_headers, sales_headers, db_session):
    """空 PO(无行)被拒 → 41608。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, _ = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)

    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD", "lines": []})
    assert r.status_code == 400, r.text
    assert r.json()["code"] == 41608


@pytest.mark.asyncio
async def test_source_so_invalid(client, purchaser_headers, sales_headers, db_session):
    """源 SO 无效(不存在或非 CONFIRMED)→ 41604。SO 恒 CONFIRMED,此处验不存在分支。"""
    sup = await create_supplier(client, purchaser_headers)
    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": 999999, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": 1, "qty": 1, "unit_price": 1}]})
    assert r.status_code == 404, r.text
    assert r.json()["code"] == 41604


@pytest.mark.asyncio
async def test_inactive_supplier_rejected(client, purchaser_headers, sales_headers, db_session):
    """停用供应商不可被新 PO 选用 → 41606。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    await client.post(f"/api/v1/suppliers/{sup['id']}/deactivate", headers=purchaser_headers)

    r = await client.post("/api/v1/purchase-orders", headers=purchaser_headers, json={
        "source_sales_order_id": so_id, "supplier_id": sup["id"], "currency": "USD",
        "lines": [{"source_sales_order_line_id": so_lines[0]["id"], "qty": 1, "unit_price": 7}]})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == 41606
