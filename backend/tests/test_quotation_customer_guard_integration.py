"""报价×停用客户写入守卫:新建/换客户拦(409 41410),存量草稿不换客户放行。

前端下拉只给 ACTIVE 挡不住直连 API,服务端硬挡(同 is_selectable_salesperson 纪律)。
"""
import pytest
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.customer import Customer, CustomerStatus
from app.db.models.sku import Sku
from app.db.models.spu import Spu


async def _seed_sku(db):
    if not (await db.execute(select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                        level=1, is_leaf=True, sort_order=0))
        await db.flush()
    spu = Spu(spu_code="SPUG001", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKUG001", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    await db.commit()
    return sku


async def _seed_customer(db, *, code, name, status=CustomerStatus.ACTIVE):
    c = Customer(code=code, name=name, status=status)
    db.add(c)
    await db.commit()
    return c


@pytest.mark.asyncio
async def test_create_quotation_with_inactive_customer_rejected(client, sales_headers, db_session):
    sku = await _seed_sku(db_session)
    dead = await _seed_customer(db_session, code="CG00001", name="停用客户",
                                status=CustomerStatus.INACTIVE)
    r = await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": dead.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 1, "qty": 1}]})
    assert r.status_code == 409, r.text
    assert r.json()["code"] == 41410


@pytest.mark.asyncio
async def test_existing_draft_saves_after_customer_deactivated(client, sales_headers, db_session):
    """客户后停用:不换客户的常规保存放行(运营可收尾,不锁旧单据)。"""
    sku = await _seed_sku(db_session)
    cust = await _seed_customer(db_session, code="CG00002", name="先活后停")
    created = (await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 1, "qty": 1}]})).json()["data"]
    oid, updated_at = created["id"], created["updated_at"]

    cust.status = CustomerStatus.INACTIVE
    await db_session.commit()

    p = await client.put(f"/api/v1/quotations/{oid}", headers=sales_headers, json={
        "customer_id": cust.id, "currency": "USD", "summary": "收尾改摘要",
        "expected_updated_at": updated_at,
        "lines": [{"sku_id": sku.id, "unit_price": 2, "qty": 1}]})
    assert p.status_code == 200, p.text


@pytest.mark.asyncio
async def test_draft_cannot_switch_to_inactive_customer(client, sales_headers, db_session):
    sku = await _seed_sku(db_session)
    alive = await _seed_customer(db_session, code="CG00003", name="在用客户")
    dead = await _seed_customer(db_session, code="CG00004", name="停用客户B",
                                status=CustomerStatus.INACTIVE)
    created = (await client.post("/api/v1/quotations", headers=sales_headers, json={
        "customer_id": alive.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 1, "qty": 1}]})).json()["data"]
    oid, updated_at = created["id"], created["updated_at"]

    p = await client.put(f"/api/v1/quotations/{oid}", headers=sales_headers, json={
        "customer_id": dead.id, "currency": "USD",
        "expected_updated_at": updated_at,
        "lines": [{"sku_id": sku.id, "unit_price": 1, "qty": 1}]})
    assert p.status_code == 409
    assert p.json()["code"] == 41410
