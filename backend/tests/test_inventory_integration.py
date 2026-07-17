"""库存增量:纯派生口径 compute_stock_balance + /inventory 端点 + SO 详情 stock_balances 块 + RBAC。

覆盖契约 §7 七项:
① 同一 SO 行拆两 PO + 两 RECEIVED 入库 → ordered_qty 不翻倍(CTE 预聚合正确性)
② 同一 SO 两销售行同 SKU → 订购量合并 + 展示字段取 SKU 当前档
③ 跨 PO 归属正确 / unreceive 后回落
④ RECEIVED-only 过滤(在途不计)
⑤ 行包含规则(默认 available>0;未入库行不进 /inventory;scope=history;SO 详情块含全部行)
⑥ RBAC:PURCHASER/SALES 200 + 无权 403 + 有 sales:read 无 inventory:read → SO 详情无 stock_balances 键
⑦ 分页与筛选
"""
import pytest
from sqlalchemy import select

from app.db.models.sku import Sku
from tests.inventory_helpers import (
    create_supplier,
    find_line,
    make_confirmed_po,
    make_confirmed_so,
    receive_inbound,
    rows_by_sku,
    seed_inventory_catalog,
)

pytestmark = pytest.mark.asyncio


async def _inventory(client, headers, **params):
    r = await client.get("/api/v1/inventory", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ─────────────────────────── ① CTE 预聚合:ordered 不翻倍 ───────────────────────────

async def test_split_two_po_two_inbound_ordered_not_doubled(
        client, db_session, sales_headers, purchaser_headers):
    """SO 行 A=1000 拆 PO1(600)+PO2(400),各建一张 RECEIVED 入库 → ordered=1000(非 2000)、inbound=1000。"""
    cust, [sku] = await seed_inventory_catalog(db_session, sku_codes=("SKUINV_A",))
    so_id, so_lines = await make_confirmed_so(
        client, sales_headers, cust, [{"sku_id": sku.id, "unit_price": "9.00", "qty": 1000}])
    so_line = so_lines[0]
    supplier = await create_supplier(client, purchaser_headers)
    po1, l1 = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": so_line["id"],
                                   "qty": 600, "unit_price": "5.00"}])
    po2, l2 = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": so_line["id"],
                                   "qty": 400, "unit_price": "5.00"}])
    await receive_inbound(client, purchaser_headers, purchase_order_id=po1,
                          lines=[{"purchase_order_line_id": l1[0]["id"], "qty": 600}])
    await receive_inbound(client, purchaser_headers, purchase_order_id=po2,
                          lines=[{"purchase_order_line_id": l2[0]["id"], "qty": 400}])

    data = await _inventory(client, purchaser_headers, sales_order_id=so_id)
    assert data["total"] == 1
    row = data["items"][0]
    assert row["ordered_qty"] == 1000.0     # 关键:未按 PO/入库分支翻倍
    assert row["inbound_qty"] == 1000.0
    assert row["outbound_qty"] == 0.0
    assert row["available_qty"] == 1000.0
    assert row["sku_code"] == "SKUINV_A"


# ─────────────────────────── ② 同 SO 两行同 SKU 合并 + 当前档展示 ───────────────────────────

async def test_two_so_lines_same_sku_merge_and_current_archive(
        client, db_session, sales_headers, purchaser_headers):
    cust, [sku] = await seed_inventory_catalog(db_session, sku_codes=("SKUINV_A",))
    so_id, so_lines = await make_confirmed_so(client, sales_headers, cust, [
        {"sku_id": sku.id, "unit_price": "9.00", "qty": 300},
        {"sku_id": sku.id, "unit_price": "9.00", "qty": 200}])
    assert len({ln["id"] for ln in so_lines}) == 2  # 两条独立 SO 行,同 SKU

    # 改 SKU 当前档品名 → 断言库存展示取的是当前档,不是行快照
    db_sku = (await db_session.execute(select(Sku).where(Sku.id == sku.id))).scalar_one()
    db_sku.name_i18n = {"zh": "改名后的当前档品名"}
    await db_session.commit()

    # SO 详情块含全部行(含已入 0),合并成一行 ordered=500
    detail = (await client.get(f"/api/v1/sales-orders/{so_id}",
                               headers=sales_headers)).json()["data"]
    blocks = detail["order"]["stock_balances"]
    assert len(blocks) == 1
    row = blocks[0]
    assert row["ordered_qty"] == 500.0          # 300 + 200 合并
    assert row["inbound_qty"] == 0.0
    assert row["name"] == "改名后的当前档品名"   # 当前档,非行快照


# ─────────────────────────── ③ 跨 PO 归属 + unreceive 回落 ───────────────────────────

async def test_cross_po_attribution_and_unreceive_rollback(
        client, db_session, sales_headers, purchaser_headers):
    cust, [sku_a, sku_b] = await seed_inventory_catalog(
        db_session, sku_codes=("SKUINV_A", "SKUINV_B"))
    so_id, so_lines = await make_confirmed_so(client, sales_headers, cust, [
        {"sku_id": sku_a.id, "unit_price": "9.00", "qty": 1000},
        {"sku_id": sku_b.id, "unit_price": "9.00", "qty": 500}])
    la = find_line(so_lines, sku_a.id)
    lb = find_line(so_lines, sku_b.id)
    supplier = await create_supplier(client, purchaser_headers)
    # PO1: A 600
    po1, p1 = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": la["id"],
                                   "qty": 600, "unit_price": "5.00"}])
    # PO2: A 400 + B 500
    po2, p2 = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[
            {"source_sales_order_line_id": la["id"], "qty": 400, "unit_price": "5.00"},
            {"source_sales_order_line_id": lb["id"], "qty": 500, "unit_price": "5.00"}])
    await receive_inbound(client, purchaser_headers, purchase_order_id=po1,
                          lines=[{"purchase_order_line_id": p1[0]["id"], "qty": 600}])
    p2_by_soline = {ln["source_sales_order_line_id"]: ln for ln in p2}
    inb2 = await receive_inbound(client, purchaser_headers, purchase_order_id=po2, lines=[
        {"purchase_order_line_id": p2_by_soline[la["id"]]["id"], "qty": 400},
        {"purchase_order_line_id": p2_by_soline[lb["id"]]["id"], "qty": 500}])

    data = await _inventory(client, purchaser_headers, sales_order_id=so_id)
    by = rows_by_sku(data["items"])
    assert by[sku_a.id]["inbound_qty"] == 1000.0   # 600(PO1) + 400(PO2)
    assert by[sku_b.id]["inbound_qty"] == 500.0    # 仅 PO2

    # 撤销 PO2 的入库 → A 回落 600、B 回落 0(B 退出默认视图)
    ur = await client.post(f"/api/v1/inbound-orders/{inb2}/unreceive",
                           headers=purchaser_headers, json={})
    assert ur.status_code == 200, ur.text
    data2 = await _inventory(client, purchaser_headers, sales_order_id=so_id)
    by2 = rows_by_sku(data2["items"])
    assert by2[sku_a.id]["inbound_qty"] == 600.0
    assert sku_b.id not in by2                      # B available=0 退出默认视图
    # SO 详情块(全部行)仍见 B ordered=500 inbound=0
    detail = (await client.get(f"/api/v1/sales-orders/{so_id}",
                               headers=sales_headers)).json()["data"]
    blk = rows_by_sku(detail["order"]["stock_balances"])
    assert blk[sku_b.id]["ordered_qty"] == 500.0 and blk[sku_b.id]["inbound_qty"] == 0.0


# ─────────────────────────── ④ RECEIVED-only(在途不计) ───────────────────────────

async def test_in_transit_not_counted(client, db_session, sales_headers, purchaser_headers):
    cust, [sku] = await seed_inventory_catalog(db_session, sku_codes=("SKUINV_A",))
    so_id, so_lines = await make_confirmed_so(
        client, sales_headers, cust, [{"sku_id": sku.id, "unit_price": "9.00", "qty": 1000}])
    supplier = await create_supplier(client, purchaser_headers)
    po, pl = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": so_lines[0]["id"],
                                   "qty": 1000, "unit_price": "5.00"}])
    # 建入库但不收货(IN_TRANSIT)
    inb = await receive_inbound(client, purchaser_headers, purchase_order_id=po,
                                lines=[{"purchase_order_line_id": pl[0]["id"], "qty": 500}],
                                receive=False)
    data = await _inventory(client, purchaser_headers, sales_order_id=so_id)
    assert data["total"] == 0   # 在途不计 → available=0 → 不进默认视图
    # SO 详情块:ordered=1000 inbound=0
    detail = (await client.get(f"/api/v1/sales-orders/{so_id}",
                               headers=sales_headers)).json()["data"]
    row = detail["order"]["stock_balances"][0]
    assert row["ordered_qty"] == 1000.0 and row["inbound_qty"] == 0.0

    # 收货后计入
    rc = await client.post(f"/api/v1/inbound-orders/{inb}/receive",
                           headers=purchaser_headers, json={})
    assert rc.status_code == 200, rc.text
    data2 = await _inventory(client, purchaser_headers, sales_order_id=so_id)
    assert data2["items"][0]["inbound_qty"] == 500.0


# ─────────────────────────── ⑤ 行包含规则 ───────────────────────────

async def test_row_inclusion_rules(client, db_session, sales_headers, purchaser_headers):
    """未入库行不进 /inventory 默认;scope=history 与默认同集(本步无出库);SO 详情块含全部行。"""
    cust, [sku_a, sku_b] = await seed_inventory_catalog(
        db_session, sku_codes=("SKUINV_A", "SKUINV_B"))
    so_id, so_lines = await make_confirmed_so(client, sales_headers, cust, [
        {"sku_id": sku_a.id, "unit_price": "9.00", "qty": 100},
        {"sku_id": sku_b.id, "unit_price": "9.00", "qty": 100}])
    la = find_line(so_lines, sku_a.id)
    supplier = await create_supplier(client, purchaser_headers)
    # 只对 A 采购并收货;B 全程未采购未入库
    po, pl = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": la["id"],
                                   "qty": 100, "unit_price": "5.00"}])
    await receive_inbound(client, purchaser_headers, purchase_order_id=po,
                          lines=[{"purchase_order_line_id": pl[0]["id"], "qty": 100}])

    # 默认 available>0:只有 A
    default = await _inventory(client, purchaser_headers, sales_order_id=so_id)
    assert set(rows_by_sku(default["items"])) == {sku_a.id}
    # scope=history:本步无出库,等同 inbound>0 → 仍只 A
    hist = await _inventory(client, purchaser_headers, sales_order_id=so_id, scope="history")
    assert set(rows_by_sku(hist["items"])) == {sku_a.id}
    # SO 详情块:A + B(含未入库 B,ordered 对照)
    detail = (await client.get(f"/api/v1/sales-orders/{so_id}",
                               headers=sales_headers)).json()["data"]
    assert set(rows_by_sku(detail["order"]["stock_balances"])) == {sku_a.id, sku_b.id}


# ─────────────────────────── ⑥ RBAC ───────────────────────────

async def test_rbac_inventory_endpoint(client, db_session, sales_headers, purchaser_headers,
                                        product_operator_headers):
    # PURCHASER 200
    r1 = await client.get("/api/v1/inventory", headers=purchaser_headers)
    assert r1.status_code == 200, r1.text
    # SALES 200
    r2 = await client.get("/api/v1/inventory", headers=sales_headers)
    assert r2.status_code == 200, r2.text
    # 无 inventory:read(PRODUCT_OPERATOR)→ 403
    r3 = await client.get("/api/v1/inventory", headers=product_operator_headers)
    assert r3.status_code == 403


async def test_admin_not_granted_inventory(client, superadmin_headers):
    """Q25 职责分离:ADMIN 不授 inventory:read → /inventory 403。"""
    r = await client.get("/api/v1/inventory", headers=superadmin_headers)
    assert r.status_code == 403


async def test_so_detail_stock_block_permission_gated(
        client, db_session, sales_headers, sales_readonly_headers):
    """SO 详情 stock_balances 块按 inventory:read 条件下发:
    有 inventory:read(SALES)→ 有键;有 sales:read 无 inventory:read → 无键(负例)。"""
    cust, [sku] = await seed_inventory_catalog(db_session, sku_codes=("SKUINV_A",))
    so_id, _ = await make_confirmed_so(
        client, sales_headers, cust, [{"sku_id": sku.id, "unit_price": "9.00", "qty": 100}])
    # SALES(持 inventory:read)→ 有块
    d1 = (await client.get(f"/api/v1/sales-orders/{so_id}",
                           headers=sales_headers)).json()["data"]
    assert "stock_balances" in d1["order"]
    # 仅 sales:read → 无块(后端脱敏,非前端隐藏)
    d2 = (await client.get(f"/api/v1/sales-orders/{so_id}",
                           headers=sales_readonly_headers)).json()["data"]
    assert "stock_balances" not in d2["order"]


# ─────────────────────────── ⑦ 分页与筛选 ───────────────────────────

async def test_pagination_and_filters(client, db_session, sales_headers, purchaser_headers):
    cust, [sku_a, sku_b] = await seed_inventory_catalog(
        db_session, sku_codes=("SKUINV_A", "SKUINV_B"))
    so_id, so_lines = await make_confirmed_so(client, sales_headers, cust, [
        {"sku_id": sku_a.id, "unit_price": "9.00", "qty": 100},
        {"sku_id": sku_b.id, "unit_price": "9.00", "qty": 100}])
    la, lb = find_line(so_lines, sku_a.id), find_line(so_lines, sku_b.id)
    supplier = await create_supplier(client, purchaser_headers)
    po, pl = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[
            {"source_sales_order_line_id": la["id"], "qty": 100, "unit_price": "5.00"},
            {"source_sales_order_line_id": lb["id"], "qty": 100, "unit_price": "5.00"}])
    pl_by = {ln["source_sales_order_line_id"]: ln for ln in pl}
    await receive_inbound(client, purchaser_headers, purchase_order_id=po, lines=[
        {"purchase_order_line_id": pl_by[la["id"]]["id"], "qty": 100},
        {"purchase_order_line_id": pl_by[lb["id"]]["id"], "qty": 100}])

    # 两行在库
    full = await _inventory(client, purchaser_headers)
    assert full["total"] >= 2
    # 分页 size=1
    p1 = await _inventory(client, purchaser_headers, sales_order_id=so_id, page=1, size=1)
    assert p1["total"] == 2 and len(p1["items"]) == 1
    # 按 sku_id 过滤
    only_a = await _inventory(client, purchaser_headers, sku_id=sku_a.id)
    assert all(it["sku_id"] == sku_a.id for it in only_a["items"])
    # q 按 sku_code
    by_code = await _inventory(client, purchaser_headers, q="SKUINV_B")
    assert all("SKUINV_B" == it["sku_code"] for it in by_code["items"]) and by_code["total"] >= 1
