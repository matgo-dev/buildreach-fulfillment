"""报价详情展示名:GET /{id} 服务端按 id 直查客户/报价人名,不受"可选报价人"口径限制——
历史报价人后来停用/改角色仍显示姓名,不退化成 #id(前端不再靠可选人列表反查)。"""
import pytest
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.user import User, UserStatus


async def _seed(db):
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()
    spu = Spu(spu_code="SPUD001", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKUD001", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    cust = Customer(code="CD00001", name="东非建材")
    db.add(cust)
    await db.commit()
    return cust, sku


@pytest.mark.asyncio
async def test_detail_shows_names_even_when_salesperson_not_selectable(
        client, sales_headers, db_session):
    cust, sku = await _seed(db_session)
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})
    oid = r.json()["data"]["id"]

    # 造一个非可选用户(无任何角色 → 无 quote:manage),把报价人历史归属改到它(模拟离职/改角色)。
    ghost = User(email="ghost@fulfillment.local", name="离职销售", password_hash="x",
                 status=UserStatus.ACTIVE, must_change_password=False)
    db_session.add(ghost)
    await db_session.flush()
    from app.db.models.quotation import QuotationOrder
    order = (await db_session.execute(
        select(QuotationOrder).where(QuotationOrder.id == oid))).scalar_one()
    order.salesperson_id = ghost.id
    await db_session.commit()

    g = (await client.get(f"/api/v1/quotations/{oid}", headers=sales_headers)).json()["data"]
    # 报价人虽已不可选,详情仍显示姓名(非 #id);客户名同样直出。
    assert g["order"]["salesperson_display"] == "离职销售"
    assert g["order"]["customer_display"] == "东非建材"
