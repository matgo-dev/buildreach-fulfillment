"""库存增量测试共用夹具助手(非 test_ 前缀,pytest 不收集)。

库存是纯派生读数:先走主流程(报价→锁档→转销售→采购→入库→收货)造出真单据链,
再断言 /inventory 与 SO 详情 stock_balances 块的聚合数字。故这里的 builder 都在造
上游单据,库存侧本身零写入。
"""
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from tests.inbound_helpers import make_confirmed_po  # noqa: F401  (re-export 便利)
from tests.purchase_helpers import create_supplier  # noqa: F401


async def seed_inventory_catalog(db, *, sku_codes=("SKUINV_A",), unit="ton",
                                 cust_code="CINV0001"):
    """建 ACTIVE catalog(1 SPU + N SKU)+ 客户。返回 (customer, [Sku...])。
    多 SKU 支撑「跨 PO 不同 SKU 归属」与「同 SO 两行同 SKU 合并」两类场景。"""
    if not (await db.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                        level=1, is_leaf=True, sort_order=0))
        await db.flush()
    spu = Spu(spu_code="SPUINV1", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    skus = []
    for code in sku_codes:
        sku = Sku(spu_id=spu.id, sku_code=code, unit=unit,
                  name_i18n={"zh": f"品名-{code}"}, created_by=1, status="ACTIVE")
        db.add(sku)
        skus.append(sku)
    cust = Customer(code=cust_code, name="库存客户")
    db.add(cust)
    await db.commit()
    for sku in skus:
        await db.refresh(sku)
    return cust, skus


async def make_confirmed_so(client, sales_headers, cust, lines):
    """报价(多行,行可指定不同 sku_id / 同 sku_id)→锁档→转销售。
    lines: [{"sku_id":.., "unit_price":.., "qty":..}]。返回 (sales_order_id, [so_line dict...])。"""
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "summary": "库存测试单", "lines": lines})
    assert r.status_code == 200, r.text
    qid = r.json()["data"]["id"]
    lk = await client.post(f"/api/v1/quotations/{qid}/lock", headers=sales_headers)
    assert lk.status_code == 200, lk.text
    conv = await client.post(f"/api/v1/quotations/{qid}/convert", headers=sales_headers)
    assert conv.status_code == 200, conv.text
    so = conv.json()["data"]["order"]
    detail = (await client.get(f"/api/v1/sales-orders/{so['id']}",
                               headers=sales_headers)).json()["data"]
    return so["id"], detail["lines"]


async def receive_inbound(client, purchaser_headers, *, purchase_order_id, lines, receive=True):
    """基于 CONFIRMED PO 建入库单,默认直接确认收货(RECEIVED)。
    lines: [{"purchase_order_line_id":.., "qty":..}]。返回 inbound_order_id。"""
    r = await client.post("/api/v1/inbound-orders", headers=purchaser_headers, json={
        "purchase_order_id": purchase_order_id, "lines": lines})
    assert r.status_code == 200, r.text
    inb_id = r.json()["data"]["order"]["id"]
    if receive:
        rc = await client.post(f"/api/v1/inbound-orders/{inb_id}/receive",
                               headers=purchaser_headers, json={})
        assert rc.status_code == 200, rc.text
    return inb_id


def find_line(so_lines, sku_id, *, nth=0):
    """从 SO 行列表里挑第 nth 个 sku_id == 目标的行(同 SKU 多行时按序取)。"""
    matches = [ln for ln in so_lines if ln["sku_id"] == sku_id]
    return matches[nth]


def rows_by_sku(items):
    """把 /inventory items 或 stock_balances 块按 sku_id 索引,便于断言。"""
    return {it["sku_id"]: it for it in items}
