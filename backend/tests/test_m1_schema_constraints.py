"""DB schema 专项评审(opus)必修项的回归:金额/范围约束的应用层 400 + DB 兜底。"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.category import Category


async def _prep_customer_and_sku(client, headers, catalog_headers, db_session):
    """headers：customer/quotation 用。catalog_headers：spu/sku 用（product:manage）。
    行校验(qty>0/price≥0)是 Pydantic 层,先于可选货门禁触发,故 SKU 不必 ACTIVE。
    """
    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    cust = (await client.post("/api/v1/customers", headers=headers,
            json={"name": "客户A"})).json()["data"]
    spu_id = (await client.post("/api/v1/spus", headers=catalog_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})).json()["data"]["id"]
    sku = (await client.post("/api/v1/skus", headers=catalog_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "DN50", "label_i18n": {"zh": "公称通径"}}]})).json()["data"]
    return cust, sku


# ── 应用层:干净 400 ──

@pytest.mark.asyncio
async def test_line_rejects_zero_qty(
    client, superadmin_headers, product_operator_headers, sales_headers, db_session
):
    cust, sku = await _prep_customer_and_sku(
        client, superadmin_headers, product_operator_headers, db_session)
    r = await client.post("/api/v1/quotations", headers=sales_headers,
                          json={"customer_id": cust["id"], "currency": "USD",
                                "lines": [{"sku_id": sku["id"], "unit_price": 100.0, "qty": 0}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_line_rejects_negative_price(
    client, superadmin_headers, product_operator_headers, sales_headers, db_session
):
    cust, sku = await _prep_customer_and_sku(
        client, superadmin_headers, product_operator_headers, db_session)
    r = await client.post("/api/v1/quotations", headers=sales_headers,
                          json={"customer_id": cust["id"], "currency": "USD",
                                "lines": [{"sku_id": sku["id"], "unit_price": -1.0, "qty": 2}]})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sku_rejects_negative_reference_price(
    client, product_operator_headers, db_session
):
    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    spu_id = (await client.post("/api/v1/spus", headers=product_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})).json()["data"]["id"]
    r = await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "reference_price": -5, "name_i18n": {"zh": "阀"},
        "spec_items": []})
    assert r.status_code == 422


# ── DB 兜底:绕过应用层直写也被约束挡住 ──

@pytest.mark.asyncio
async def test_db_check_rejects_bad_category_level(db_session):
    db_session.add(Category(code="99", parent_code=None, name_i18n={"zh": "x"},
                            level=0, is_leaf=True, sort_order=0))
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ── M1 地基回补(0009):status / currency DB 兜底 ──

@pytest.mark.asyncio
async def test_db_check_rejects_bad_customer_status(db_session):
    from app.db.models.customer import Customer
    db_session.add(Customer(code="C999999", name="x", status="PENDING"))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_db_check_rejects_non_iso4217_currency(db_session, superadmin_headers):
    from app.core.config import settings
    from app.db.models.user import User
    from app.db.models.customer import Customer
    from app.db.models.quotation import QuotationOrder
    uid = (await db_session.execute(
        select(User.id).where(User.email == settings.SUPER_ADMIN_EMAIL))).scalar_one()
    cust = Customer(code="C888888", name="x", status="ACTIVE")
    db_session.add(cust)
    await db_session.flush()
    # 中文/小写/非三字母币种被 DB 挡住(currency ~ '^[A-Z]{3}$')
    db_session.add(QuotationOrder(no="Q-BAD-CUR", customer_id=cust.id, currency="美元",
                                  status="DRAFT", created_by=uid, salesperson_id=uid))
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_db_check_rejects_nonpositive_next_seq(db_session):
    from app.db.models.number_sequence import NumberSequence
    # 号段计数器 gapless-from-1;直写 0/负数被 DB 挡(next_seq >= 1)
    db_session.add(NumberSequence(scope="TEST", period="", next_seq=0))
    with pytest.raises(IntegrityError):
        await db_session.flush()
