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
from app.db.models.stock import InventoryBalance, InventoryMovement, InventoryMovementType
from tests.inventory_helpers import (
    create_supplier,
    find_line,
    make_confirmed_po,
    make_confirmed_so,
    receive_inbound,
    rows_by_sku,
    seed_inventory_catalog,
)
from tests.outbound_helpers import create_and_confirm_outbound, create_shipment

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


# ─────────────────────────── ② 库存展示取 SKU 当前档(非行快照)───────────────────────────
# 原「同 SO 两行同 SKU 合并」场景在 §0-11(UNIQUE(sales_order_id, sku_id))后结构性消失
# ——一 SKU 至多一 SO 行,故本例改为单行验「当前档展示」这一保留语义(合并按 (so,sku) 聚合仍在,
# 但不再由多 SO 行触发)。

async def test_stock_balance_shows_current_archive_not_snapshot(
        client, db_session, sales_headers, purchaser_headers):
    cust, [sku] = await seed_inventory_catalog(db_session, sku_codes=("SKUINV_A",))
    so_id, so_lines = await make_confirmed_so(client, sales_headers, cust, [
        {"sku_id": sku.id, "unit_price": "9.00", "qty": 500}])
    assert len(so_lines) == 1

    # 改 SKU 当前档品名 → 断言库存展示取的是当前档,不是行快照
    db_sku = (await db_session.execute(select(Sku).where(Sku.id == sku.id))).scalar_one()
    db_sku.name_i18n = {"zh": "改名后的当前档品名"}
    await db_session.commit()

    # SO 详情块含全部行(含已入 0),(so,sku) 一行 ordered=500
    detail = (await client.get(f"/api/v1/sales-orders/{so_id}",
                               headers=sales_headers)).json()["data"]
    blocks = detail["order"]["stock_balances"]
    assert len(blocks) == 1
    row = blocks[0]
    assert row["ordered_qty"] == 500.0
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


async def test_scope_all_rejected_by_endpoint(client, purchaser_headers):
    """ALL 仅内部(SO 详情块)口径,端点不可达:scope=all → 422(PAGE_SCOPES 派生 pattern 拦截)。"""
    r = await client.get("/api/v1/inventory", headers=purchaser_headers,
                         params={"scope": "all"})
    assert r.status_code == 422


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
    # 分页 size=1:首页/末页非空,total 随 count(*) OVER () 一趟返回
    p1 = await _inventory(client, purchaser_headers, sales_order_id=so_id, page=1, size=1)
    assert p1["total"] == 2 and len(p1["items"]) == 1
    p2 = await _inventory(client, purchaser_headers, sales_order_id=so_id, page=2, size=1)
    assert p2["total"] == 2 and len(p2["items"]) == 1
    # 越界空页:窗口无行可取 → 回落单独 count,total 仍为 2(不塌成 0)
    over = await _inventory(client, purchaser_headers, sales_order_id=so_id, page=99, size=1)
    assert over["items"] == [] and over["total"] == 2
    # 按 sku_id 过滤
    only_a = await _inventory(client, purchaser_headers, sku_id=sku_a.id)
    assert all(it["sku_id"] == sku_a.id for it in only_a["items"])
    # q 按 sku_code
    by_code = await _inventory(client, purchaser_headers, q="SKUINV_B")
    assert all("SKUINV_B" == it["sku_code"] for it in by_code["items"]) and by_code["total"] >= 1


# ─────────────────── ⑧ 内部读投影按界面语言,不随单据语言漂 ───────────────────

async def test_internal_projection_renders_ui_language_not_document_language(
        client, db_session, sales_headers, purchaser_headers):
    """英文销售单(customer.quote_language='en')的库存行,展示三件套仍是中文。

    SalesOrder.language 是「发给客户的单据语言」,只该管报价单/形式发票等对外输出;
    库存页是内部中文运营界面,拿单据语言渲染会让同一列表里中英混排(实测:单位列
    一行「件」一行「bag」)。故内部读投影固定按界面语言渲染。
    """
    cust, [sku] = await seed_inventory_catalog(
        db_session, sku_codes=("SKUINV_EN",), unit="bag", cust_code="CINV_EN",
        quote_language="en", sku_name_i18n={"zh": "工字钢", "en": "I-beam"})
    so_id, so_lines = await make_confirmed_so(
        client, sales_headers, cust, [{"sku_id": sku.id, "unit_price": "9.00", "qty": 10}])
    sup = await create_supplier(client, purchaser_headers)
    po_id, po_lines = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=sup, lines=[{"source_sales_order_line_id": so_lines[0]["id"],
                              "qty": 10, "unit_price": "5.00"}])
    await receive_inbound(client, purchaser_headers,
                          purchase_order_id=po_id,
                          lines=[{"purchase_order_line_id": po_lines[0]["id"], "qty": 10}])

    page = await _inventory(client, sales_headers, sales_order_id=so_id)
    row = rows_by_sku(page["items"])[sku.id]
    assert row["unit"] == "包", f"单位应按界面语言取中文,实得 {row['unit']!r}"
    assert row["name"] == "工字钢", f"品名应按界面语言取中文,实得 {row['name']!r}"


async def test_stock_movements_and_balance_are_persisted(
        client, db_session, sales_headers, purchaser_headers, logistics_headers):
    """库存落库:确认入库/撤销入库/重收/确认出库都写流水,余额保持销售单维度。"""
    cust, [sku] = await seed_inventory_catalog(db_session, sku_codes=("SKUINV_LEDGER",))
    so_id, so_lines = await make_confirmed_so(
        client, sales_headers, cust, [{"sku_id": sku.id, "unit_price": "9.00", "qty": 10}])
    supplier = await create_supplier(client, purchaser_headers)
    po_id, po_lines = await make_confirmed_po(
        client, purchaser_headers, source_sales_order_id=so_id, so_lines=so_lines,
        supplier=supplier, lines=[{"source_sales_order_line_id": so_lines[0]["id"],
                                   "qty": 10, "unit_price": "5.00"}])

    inbound_id = await receive_inbound(
        client, purchaser_headers, purchase_order_id=po_id,
        lines=[{"purchase_order_line_id": po_lines[0]["id"], "qty": 10}])
    balance = (await db_session.execute(select(InventoryBalance).where(
        InventoryBalance.sales_order_id == so_id, InventoryBalance.sku_id == sku.id))).scalar_one()
    assert float(balance.inbound_qty) == 10.0
    assert float(balance.outbound_qty) == 0.0
    assert float(balance.available_qty) == 10.0
    movements = list((await db_session.execute(
        select(InventoryMovement).where(
            InventoryMovement.sales_order_id == so_id,
            InventoryMovement.sku_id == sku.id,
        ).order_by(InventoryMovement.id))).scalars().all())
    assert [m.movement_type for m in movements] == [InventoryMovementType.INBOUND_RECEIVE]
    assert [float(m.qty_delta) for m in movements] == [10.0]

    ur = await client.post(f"/api/v1/inbound-orders/{inbound_id}/unreceive",
                           headers=purchaser_headers, json={"void_reason": "重收测试"})
    assert ur.status_code == 200, ur.text
    await db_session.refresh(balance)
    assert float(balance.inbound_qty) == 0.0
    assert float(balance.available_qty) == 0.0

    rc = await client.post(f"/api/v1/inbound-orders/{inbound_id}/receive",
                           headers=purchaser_headers, json={})
    assert rc.status_code == 200, rc.text
    ship = await create_shipment(client, logistics_headers)
    _, conf = await create_and_confirm_outbound(
        client, logistics_headers, sales_order_id=so_id, shipment_id=ship["id"],
        lines=[{"sales_order_line_id": so_lines[0]["id"], "qty": 4}])
    assert conf.status_code == 200, conf.text

    await db_session.refresh(balance)
    assert float(balance.inbound_qty) == 10.0
    assert float(balance.outbound_qty) == 4.0
    assert float(balance.available_qty) == 6.0
    movements = list((await db_session.execute(
        select(InventoryMovement).where(
            InventoryMovement.sales_order_id == so_id,
            InventoryMovement.sku_id == sku.id,
        ).order_by(InventoryMovement.id))).scalars().all())
    assert [m.movement_type for m in movements] == [
        InventoryMovementType.INBOUND_RECEIVE,
        InventoryMovementType.INBOUND_UNRECEIVE,
        InventoryMovementType.INBOUND_RECEIVE,
        InventoryMovementType.OUTBOUND_ISSUE,
    ]
    assert [float(m.qty_delta) for m in movements] == [10.0, -10.0, 10.0, -4.0]
