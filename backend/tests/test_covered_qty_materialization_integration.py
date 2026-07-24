"""covered_qty 物化落列(方案C):sales_order_lines.covered_qty 冗余列 =
Σ(非 CANCELLED PO 行 qty,含 DRAFT),采购三写入口同事务重算写回;列表进度下推 SQL。

断言的是**存储列**(非 compute_covered_qty 实时值),并逐处校验列 == 实时口径(单一物化源不漂移)。
真·并发锁序由 FOR UPDATE 代码 + 设计评审保证(savepoint 单连接夹具无法起两连接竞态,
与既有超采守卫同处理):此处测**功能收敛**——每次写入口后列恢复真值,含 save 删行释放旧行。
"""
import pytest
from sqlalchemy import delete, select

from app.db.models.sales_order import SalesOrder, SalesOrderLine
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.services.purchase_order_service import compute_covered_qty
from tests.purchase_helpers import (
    create_supplier,
    make_confirmed_sales_order,
    seed_catalog_and_customer,
)


async def _covered_col(db, so_line_id):
    """读**存储列** covered_qty(非实时重算)。"""
    return float((await db.execute(
        select(SalesOrderLine.covered_qty).where(SalesOrderLine.id == so_line_id))).scalar_one())


async def _assert_col_matches_live(db, so_line_id):
    """存储列 == compute_covered_qty 实时口径(单一物化源不漂移)。"""
    col = await _covered_col(db, so_line_id)
    live = float((await compute_covered_qty(db, [so_line_id]))[so_line_id])
    assert col == live, f"covered_qty 列 {col} != 实时口径 {live}"


async def _second_sku(db):
    """同 category 第二个 SKU(用于多行 SO;uq_slines_order_sku 要求一 SKU 一行)。"""
    spu = Spu(spu_code="SPUB001", category_code="10", name_i18n={"zh": "槽钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKUB001", unit="ton", name_i18n={"zh": "槽钢100"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    await db.commit()
    return sku


async def _po(client, H, so_id, sup_id, lines):
    """lines: [{"source_sales_order_line_id":.., "qty":..}]。unit_price 补 7。"""
    return await client.post("/api/v1/purchase-orders", headers=H, json={
        "source_sales_order_id": so_id, "supplier_id": sup_id, "currency": "USD",
        "lines": [{**ln, "unit_price": 7} for ln in lines]})


# ---------- 写入口:重算写回 ----------

@pytest.mark.asyncio
async def test_create_writes_covered_qty_column(client, purchaser_headers, sales_headers, db_session):
    """create_order 后:被采 so_line 的存储列 covered_qty = 采购量。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    lid = so_lines[0]["id"]

    assert (await _po(client, purchaser_headers, so_id, sup["id"],
                      [{"source_sales_order_line_id": lid, "qty": 2}])).status_code == 200
    assert await _covered_col(db_session, lid) == 2
    await _assert_col_matches_live(db_session, lid)


@pytest.mark.asyncio
async def test_save_updates_covered_qty_column(client, purchaser_headers, sales_headers, db_session):
    """save_order 改量后:存储列刷新到新量(重算非自增)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    lid = so_lines[0]["id"]
    r = await _po(client, purchaser_headers, so_id, sup["id"],
                  [{"source_sales_order_line_id": lid, "qty": 2}])
    po = r.json()["data"]["order"]

    save = await client.put(f"/api/v1/purchase-orders/{po['id']}", headers=purchaser_headers, json={
        "supplier_id": sup["id"], "currency": "USD", "expected_updated_at": po["updated_at"],
        "lines": [{"source_sales_order_line_id": lid, "qty": 4, "unit_price": 7}]})
    assert save.status_code == 200, save.text
    assert await _covered_col(db_session, lid) == 4
    await _assert_col_matches_live(db_session, lid)


@pytest.mark.asyncio
async def test_save_removing_a_line_refreshes_freed_soline(client, purchaser_headers,
                                                           sales_headers, db_session):
    """P1 回归:save 删掉某 PO 行,被释放的 so_line 存储列必须刷回真值(0),不留陈旧。
    没锁旧行 ∪ 只刷新新 payload 的实现会让被删行的 covered_qty 卡在旧值。"""
    cust, skuA = await seed_catalog_and_customer(db_session)
    skuB = await _second_sku(db_session)
    # 两行 SO(两 SKU)
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "summary": "两行单",
        "lines": [{"sku_id": skuA.id, "unit_price": 100, "qty": 5},
                  {"sku_id": skuB.id, "unit_price": 100, "qty": 5}]})
    qid = r.json()["data"]["id"]
    await client.post(f"/api/v1/quotations/{qid}/lock", headers=sales_headers)
    so = (await client.post(f"/api/v1/quotations/{qid}/convert",
                            headers=sales_headers)).json()["data"]["order"]
    so_id = so["id"]
    lines = (await client.get(f"/api/v1/sales-orders/{so_id}",
                              headers=sales_headers)).json()["data"]["lines"]
    lidA, lidB = lines[0]["id"], lines[1]["id"]
    sup = await create_supplier(client, purchaser_headers)

    # PO 覆盖两行
    po = (await _po(client, purchaser_headers, so_id, sup["id"],
                    [{"source_sales_order_line_id": lidA, "qty": 5},
                     {"source_sales_order_line_id": lidB, "qty": 5}])).json()["data"]["order"]
    assert await _covered_col(db_session, lidA) == 5
    assert await _covered_col(db_session, lidB) == 5

    # save 删掉 B 行(payload 只留 A)
    save = await client.put(f"/api/v1/purchase-orders/{po['id']}", headers=purchaser_headers, json={
        "supplier_id": sup["id"], "currency": "USD", "expected_updated_at": po["updated_at"],
        "lines": [{"source_sales_order_line_id": lidA, "qty": 5, "unit_price": 7}]})
    assert save.status_code == 200, save.text
    assert await _covered_col(db_session, lidA) == 5
    assert await _covered_col(db_session, lidB) == 0   # 被释放:必须刷回 0
    await _assert_col_matches_live(db_session, lidB)


@pytest.mark.asyncio
async def test_cancel_resets_covered_qty_column(client, purchaser_headers, sales_headers, db_session):
    """cancel_order 后:该 PO 覆盖的 so_line 存储列刷回(排除 CANCELLED)。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    lid = so_lines[0]["id"]
    po = (await _po(client, purchaser_headers, so_id, sup["id"],
                    [{"source_sales_order_line_id": lid, "qty": 5}])).json()["data"]["order"]
    assert await _covered_col(db_session, lid) == 5

    await client.post(f"/api/v1/purchase-orders/{po['id']}/cancel", headers=purchaser_headers)
    assert await _covered_col(db_session, lid) == 0
    await _assert_col_matches_live(db_session, lid)


@pytest.mark.asyncio
async def test_confirm_does_not_change_covered_qty(client, purchaser_headers, sales_headers, db_session):
    """confirm(DRAFT→CONFIRMED)两态均非 CANCELLED,covered 不动——不写回、值不变。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, so_lines = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    sup = await create_supplier(client, purchaser_headers)
    lid = so_lines[0]["id"]
    po = (await _po(client, purchaser_headers, so_id, sup["id"],
                    [{"source_sales_order_line_id": lid, "qty": 3}])).json()["data"]["order"]
    assert await _covered_col(db_session, lid) == 3

    c = await client.post(f"/api/v1/purchase-orders/{po['id']}/confirm", headers=purchaser_headers)
    assert c.status_code == 200, c.text
    assert await _covered_col(db_session, lid) == 3
    await _assert_col_matches_live(db_session, lid)


# ---------- 列表下推:空行不消失 + 分页/筛选正确 ----------

@pytest.mark.asyncio
async def test_empty_line_so_not_dropped_from_list(client, purchaser_headers, sales_headers, db_session):
    """P1 回归:零行 SO 以 NOT_ORDERED 出现在列表并计入 total(LEFT JOIN,非 inner)。
    零行 CONFIRMED SO 现流程不可达,白盒删行模拟,钉住 LATERAL 外连接不吞行。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    so_id, _ = await make_confirmed_sales_order(
        client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
    # 白盒删空该 SO 的行
    await db_session.execute(delete(SalesOrderLine).where(SalesOrderLine.sales_order_id == so_id))
    await db_session.commit()

    lst = (await client.get("/api/v1/sales-orders?status=CONFIRMED",
                            headers=purchaser_headers)).json()["data"]
    prog = {it["id"]: it["purchase_progress"] for it in lst["items"]}
    assert so_id in prog and prog[so_id] == "NOT_ORDERED"

    # purchasable_only 也应含它(≠FULLY_ORDERED)
    pur = (await client.get("/api/v1/sales-orders?status=CONFIRMED&purchasable_only=true",
                            headers=purchaser_headers)).json()["data"]
    assert so_id in {it["id"] for it in pur["items"]}


@pytest.mark.asyncio
async def test_progress_filter_pagination_total_and_slice(client, purchaser_headers,
                                                          sales_headers, db_session):
    """筛选路径下推后:total = 匹配数、切片 = size,分页无空洞。
    3 个 NOT_ORDERED SO,?purchase_progress=NOT_ORDERED&size=2 → total=3,首页 2 项。"""
    cust, sku = await seed_catalog_and_customer(db_session)
    ids = []
    for _ in range(3):
        so_id, _l = await make_confirmed_sales_order(
            client, sales_headers, cust, sku, lines=[{"unit_price": 100, "qty": 5}])
        ids.append(so_id)

    r = (await client.get(
        "/api/v1/sales-orders?status=CONFIRMED&purchase_progress=NOT_ORDERED&size=2&page=1",
        headers=purchaser_headers)).json()["data"]
    assert r["total"] == 3
    assert len(r["items"]) == 2
    assert all(it["purchase_progress"] == "NOT_ORDERED" for it in r["items"])
    page2 = (await client.get(
        "/api/v1/sales-orders?status=CONFIRMED&purchase_progress=NOT_ORDERED&size=2&page=2",
        headers=purchaser_headers)).json()["data"]
    assert len(page2["items"]) == 1
    # 两页 id 不重叠、并集 = 全部匹配
    assert set(it["id"] for it in r["items"]) | set(it["id"] for it in page2["items"]) == set(ids)
