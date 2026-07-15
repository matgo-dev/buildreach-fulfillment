"""报价人写入口守卫:salesperson_id 必须是"可选报价人"(ACTIVE + quote:manage),
前端下拉挡不住直连 API,服务端硬挡(同 /users/selectable 口径)。"""
import pytest
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.user import User


async def _seed(db):
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()
    spu = Spu(spu_code="SPUS001", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKUS001", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    cust = Customer(code="CS00001", name="客户")
    db.add(cust)
    await db.commit()
    return cust, sku


@pytest.mark.asyncio
async def test_reject_salesperson_without_quote_manage(
        client, sales_headers, product_operator_headers, db_session):
    # product_operator_headers 建了"商品运营"(无 quote:manage);把报价人指给它 → 400。
    cust, sku = await _seed(db_session)
    op = (await db_session.execute(
        select(User).where(User.email == "product_op@fulfillment.local"))).scalar_one()
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "salesperson_id": op.id,
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})
    assert r.status_code == 400, r.text
    assert r.json()["code"] == 41408


@pytest.mark.asyncio
async def test_accept_explicit_selectable_salesperson(client, sales_headers, db_session):
    # 显式指给本销售(ACTIVE + quote:manage,自己也是可选报价人)→ 200。
    cust, sku = await _seed(db_session)
    sp = (await db_session.execute(
        select(User).where(User.email == "sales@fulfillment.local"))).scalar_one()
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "salesperson_id": sp.id,
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["salesperson_id"] == sp.id
