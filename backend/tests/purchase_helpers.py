"""采购增量测试共用夹具助手(非 test_ 前缀,pytest 不收集)。

建 CONFIRMED 销售单的唯一路径 = 报价→锁档→转销售(复用主流程),供采购测试取 so_line。
"""
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.sku import Sku
from app.db.models.spu import Spu


async def seed_catalog_and_customer(db, *, reference_price=None):
    """建 ACTIVE catalog(可带 sku.reference_price 作采购建议价)+ 客户。返回 (customer, sku)。"""
    if not (await db.execute(select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                        level=1, is_leaf=True, sort_order=0))
        await db.flush()
    spu = Spu(spu_code="SPUA001", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKUA001", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE", reference_price=reference_price)
    db.add(sku)
    cust = Customer(code="CA00001", name="客户A")
    db.add(cust)
    await db.commit()
    return cust, sku


async def make_confirmed_sales_order(client, sales_headers, cust, sku, *, lines):
    """报价(给定行)→锁档→转销售,返回 (sales_order_id, [so_line dict...])。
    lines: [{"unit_price": .., "qty": ..}, ...]。"""
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "summary": "采购测试单",
        "lines": [{"sku_id": sku.id, **ln} for ln in lines]})
    assert r.status_code == 200, r.text
    qid = r.json()["data"]["id"]
    lk = await client.post(f"/api/v1/quotations/{qid}/lock", headers=sales_headers)
    assert lk.status_code == 200, lk.text
    conv = await client.post(f"/api/v1/quotations/{qid}/convert", headers=sales_headers)
    assert conv.status_code == 200, conv.text
    so = conv.json()["data"]["order"]
    detail = (await client.get(f"/api/v1/sales-orders/{so['id']}", headers=sales_headers)).json()["data"]
    return so["id"], detail["lines"]


async def create_supplier(client, purchaser_headers, *, name="供应商甲", default_currency="USD"):
    """建 ACTIVE 供应商,返回 supplier dict。"""
    r = await client.post("/api/v1/suppliers", headers=purchaser_headers,
                          json={"name": name, "default_currency": default_currency})
    assert r.status_code == 200, r.text
    return r.json()["data"]
