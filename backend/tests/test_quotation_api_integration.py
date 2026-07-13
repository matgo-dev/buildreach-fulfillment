"""T8 报价 API:8 端点整单化(create/get/list/put/delete/lock/unlock/void)+ 删旧 /lines。"""
import pytest
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.sku import Sku
from app.db.models.spu import Spu


async def _seed_active(db):
    """直接建 ACTIVE catalog + 客户(报价选料要求可选货)。"""
    if not (await db.execute(select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                        level=1, is_leaf=True, sort_order=0))
        await db.flush()
    spu = Spu(spu_code="SPUA001", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKUA001", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    cust = Customer(code="CA00001", name_i18n={"zh": "客户A"})
    db.add(cust)
    await db.commit()
    return cust, sku


@pytest.mark.asyncio
async def test_quotation_full_lifecycle_api(client, superadmin_headers, db_session):
    cust, sku = await _seed_active(db_session)
    H = superadmin_headers

    # create(整单:表头 + 2 行)
    r = await client.post("/api/v1/quotations", headers=H, json={
        "customer_id": cust.id, "currency": "USD", "summary": "Q3 钢材",
        "lines": [{"sku_id": sku.id, "unit_price": 100, "qty": 2},
                  {"sku_id": sku.id, "unit_price": 50, "qty": 1}]})
    assert r.status_code == 200, r.text
    order = r.json()["data"]
    oid = order["id"]
    assert str(order["total_amount"]) in ("250.00", "250.0") or float(order["total_amount"]) == 250
    assert order["salesperson_id"] == 1 and order["summary"] == "Q3 钢材"

    # get
    g = (await client.get(f"/api/v1/quotations/{oid}", headers=H)).json()["data"]
    assert len(g["lines"]) == 2
    updated_at = g["order"]["updated_at"]

    # list
    lst = (await client.get("/api/v1/quotations?status=DRAFT", headers=H)).json()["data"]
    assert lst["total"] >= 1 and any(it["id"] == oid for it in lst["items"])

    # put(删一行 + 改一行,带乐观锁)
    line_ids = [ln["id"] for ln in g["lines"]]
    p = await client.put(f"/api/v1/quotations/{oid}", headers=H, json={
        "customer_id": cust.id, "currency": "USD", "expected_updated_at": updated_at,
        "lines": [{"id": line_ids[0], "sku_id": sku.id, "unit_price": 100, "qty": 3}]})
    assert p.status_code == 200, p.text
    assert float(p.json()["data"]["total_amount"]) == 300

    # 旧 /lines 端点已删
    old = await client.post(f"/api/v1/quotations/{oid}/lines", headers=H,
                            json={"sku_id": sku.id, "unit_price": 1, "qty": 1})
    assert old.status_code in (404, 405)

    # lock → unlock → void
    assert (await client.post(f"/api/v1/quotations/{oid}/lock", headers=H)
            ).json()["data"]["status"] == "LOCKED"
    assert (await client.post(f"/api/v1/quotations/{oid}/unlock", headers=H)
            ).json()["data"]["status"] == "DRAFT"
    assert (await client.post(f"/api/v1/quotations/{oid}/void", headers=H,
                              json={"reason": "取消"})).json()["data"]["status"] == "VOID"


@pytest.mark.asyncio
async def test_create_language_defaults_from_customer(client, superadmin_headers, db_session):
    _, sku = await _seed_active(db_session)
    cust = Customer(code="CA00002", name_i18n={"zh": "斯语客户"}, quote_language="sw")
    db_session.add(cust)
    await db_session.commit()
    r = await client.post("/api/v1/quotations", headers=superadmin_headers, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["language"] == "sw"   # 报价单继承客户报价语言


@pytest.mark.asyncio
async def test_delete_only_draft(client, superadmin_headers, db_session):
    cust, sku = await _seed_active(db_session)
    H = superadmin_headers
    oid = (await client.post("/api/v1/quotations", headers=H, json={
        "customer_id": cust.id, "currency": "USD",
        "lines": [{"sku_id": sku.id, "unit_price": 10, "qty": 1}]})).json()["data"]["id"]
    # 锁档后不可删
    await client.post(f"/api/v1/quotations/{oid}/lock", headers=H)
    assert (await client.delete(f"/api/v1/quotations/{oid}", headers=H)).status_code == 409
    # 解锁回草稿后可删
    await client.post(f"/api/v1/quotations/{oid}/unlock", headers=H)
    assert (await client.delete(f"/api/v1/quotations/{oid}", headers=H)).status_code == 200
