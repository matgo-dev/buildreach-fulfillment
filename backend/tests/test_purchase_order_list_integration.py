"""采购单列表筛选:来源销售单号(部分匹配)+ 供应商 + 状态 + q 合并搜 + 仅可收。"""
import pytest

from tests.inbound_helpers import setup_confirmed_po
from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)


async def _receive(client, purchaser_headers, po_id, po_line_id, qty):
    """建入库单并确认,把某 PO 行收 qty(收满则该 PO 变 FULLY_RECEIVED,部分则 PARTIALLY)。"""
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_line_id, "qty": qty}]})
    assert cr.status_code == 200, cr.text
    inb_id = cr.json()["data"]["order"]["id"]
    rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive",
                           headers=purchaser_headers, json={})
    assert rc.status_code == 200, rc.text


async def _inbound_in_transit(client, purchaser_headers, po_id, po_line_id, qty):
    """建入库单但**不确认收货** → 停在 IN_TRANSIT(在途);占守卫额度但不算已收。"""
    cr = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": po_id,
        "lines": [{"purchase_order_line_id": po_line_id, "qty": qty}]})
    assert cr.status_code == 200, cr.text
    return cr.json()["data"]["order"]["id"]


async def _po(client, H, so_id, sup_id, lid, qty=2):
    r = await client.post("/api/v1/purchase-orders", headers=H, json={
        "source_sales_order_id": so_id, "supplier_id": sup_id, "currency": "USD",
        "lines": [{"source_sales_order_line_id": lid, "qty": qty, "unit_price": 7}]})
    assert r.status_code == 200, r.text
    return r.json()["data"]["order"]


@pytest.mark.asyncio
async def test_filter_by_source_sales_order_no(client, purchaser_headers, sales_headers, db_session):
    """?source_sales_order_no 部分匹配来源 SO 单号,total 随之收敛(过滤在分页前)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    soA, la = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    soB, lb = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    poA = await _po(client, purchaser_headers, soA, sup["id"], la[0]["id"])
    await _po(client, purchaser_headers, soB, sup["id"], lb[0]["id"])

    # 取 SO-A 的单号,按它筛选采购单列表
    so_a_no = (await client.get(f"/api/v1/sales-orders/{soA}", headers=sales_headers)
               ).json()["data"]["order"]["no"]
    res = (await client.get(
        f"/api/v1/purchase-orders?source_sales_order_no={so_a_no}",
        headers=purchaser_headers)).json()["data"]
    assert res["total"] == 1
    assert res["items"][0]["id"] == poA["id"]
    assert res["items"][0]["source_sales_order_no"] == so_a_no


@pytest.mark.asyncio
async def test_filter_partial_match(client, purchaser_headers, sales_headers, db_session):
    """部分匹配:用 SO 号前缀('SO2026...')能命中(ilike 子串)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so, la = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    await _po(client, purchaser_headers, so, sup["id"], la[0]["id"])

    res = (await client.get(
        "/api/v1/purchase-orders?source_sales_order_no=SO2026",
        headers=purchaser_headers)).json()["data"]
    assert res["total"] >= 1
    assert all(it["source_sales_order_no"].startswith("SO2026") for it in res["items"])


@pytest.mark.asyncio
async def test_q_matches_po_number(client, purchaser_headers, sales_headers, db_session):
    """?q 合并搜:按采购单号命中(选单器一个框既可搜 PO 号也可搜来源 SO 号)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so, la = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    po = await _po(client, purchaser_headers, so, sup["id"], la[0]["id"])

    res = (await client.get(
        f"/api/v1/purchase-orders?q={po['no']}", headers=purchaser_headers)).json()["data"]
    assert res["total"] == 1
    assert res["items"][0]["id"] == po["id"]


@pytest.mark.asyncio
async def test_q_matches_source_so_number(client, purchaser_headers, sales_headers, db_session):
    """?q 合并搜:同一个框按来源 SO 号也能命中。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so, la = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    po = await _po(client, purchaser_headers, so, sup["id"], la[0]["id"])
    so_no = (await client.get(f"/api/v1/sales-orders/{so}", headers=sales_headers)
             ).json()["data"]["order"]["no"]

    res = (await client.get(
        f"/api/v1/purchase-orders?q={so_no}", headers=purchaser_headers)).json()["data"]
    assert res["total"] == 1
    assert res["items"][0]["id"] == po["id"]


@pytest.mark.asyncio
async def test_receivable_only_hides_fully_received(
        client, purchaser_headers, sales_headers, db_session):
    """?receivable_only=true 隐藏已全部入库的 PO,保留还有未收量的(选单器默认口径)。
    过滤在分页前,total 随之收敛;与 receipt_progress 徽标一致。"""
    # 同一 catalog 只 seed 一次(seed_catalog_and_customer 用固定 SPU code,二次会撞唯一键),
    # 由两张 SO 各建一张 PO:PO_open 整单未收(NOT_RECEIVED)、PO_full 全部收满(FULLY_RECEIVED)。
    cust, sku = await seed_catalog_and_customer(db_session)
    sup = await create_supplier(client, purchaser_headers)
    so_open, lo = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 4}])
    so_full, lf = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 6}])
    open_po = await _po(client, purchaser_headers, so_open, sup["id"], lo[0]["id"], qty=4)
    full_po = await _po(client, purchaser_headers, so_full, sup["id"], lf[0]["id"], qty=6)
    open_id, full_id = open_po["id"], full_po["id"]
    for po_id in (open_id, full_id):
        await client.post(f"/api/v1/purchase-orders/{po_id}/confirm", headers=purchaser_headers)
    full_line_id = (await client.get(f"/api/v1/purchase-orders/{full_id}",
                                     headers=purchaser_headers)).json()["data"]["lines"][0]["id"]
    await _receive(client, purchaser_headers, full_id, full_line_id, 6)

    ids_all = {it["id"] for it in (await client.get(
        "/api/v1/purchase-orders?status=CONFIRMED&size=100",
        headers=purchaser_headers)).json()["data"]["items"]}
    assert {open_id, full_id} <= ids_all  # 不带 receivable_only 时两张都在

    recv = (await client.get(
        "/api/v1/purchase-orders?status=CONFIRMED&receivable_only=true&size=100",
        headers=purchaser_headers)).json()["data"]
    ids_recv = {it["id"] for it in recv["items"]}
    assert open_id in ids_recv          # 未收满 → 保留
    assert full_id not in ids_recv      # 已收满 → 隐藏


@pytest.mark.asyncio
async def test_receivable_only_keeps_partially_received(
        client, purchaser_headers, sales_headers, db_session):
    """部分入库(PARTIALLY_RECEIVED)仍有未收量 → receivable_only 下保留。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    await _receive(client, purchaser_headers, po_id, po_lines[0]["id"], 4)  # 收 4/10

    recv = (await client.get(
        "/api/v1/purchase-orders?status=CONFIRMED&receivable_only=true&size=100",
        headers=purchaser_headers)).json()["data"]
    assert po_id in {it["id"] for it in recv["items"]}


@pytest.mark.asyncio
async def test_receivable_only_hides_fully_in_transit(
        client, purchaser_headers, sales_headers, db_session):
    """整单已被在途 ASN(IN_TRANSIT,未收货)开满 → receivable_only 隐藏。
    口径必须镜像入库守卫(含在途),否则选进去真建入库时撞 41703 无额度。
    旧口径(仅 RECEIVED)会漏放行——本测试是新旧口径的判别点。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    # 在途开满 10、不收货:守卫口径 inbounded=10=qty → 无可开额度。
    await _inbound_in_transit(client, purchaser_headers, po_id, po_lines[0]["id"], 10)

    recv = (await client.get(
        "/api/v1/purchase-orders?status=CONFIRMED&receivable_only=true&size=100",
        headers=purchaser_headers)).json()["data"]
    assert po_id not in {it["id"] for it in recv["items"]}


@pytest.mark.asyncio
async def test_receivable_only_keeps_partially_in_transit(
        client, purchaser_headers, sales_headers, db_session):
    """部分在途(4/10)仍有 6 可开额度 → receivable_only 保留(不因引入守卫口径而误伤)。"""
    po_id, po_lines = await setup_confirmed_po(
        client, db_session, sales_headers, purchaser_headers, so_qty=10)
    await _inbound_in_transit(client, purchaser_headers, po_id, po_lines[0]["id"], 4)

    recv = (await client.get(
        "/api/v1/purchase-orders?status=CONFIRMED&receivable_only=true&size=100",
        headers=purchaser_headers)).json()["data"]
    assert po_id in {it["id"] for it in recv["items"]}
