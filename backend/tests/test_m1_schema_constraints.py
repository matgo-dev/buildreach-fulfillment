"""DB schema 专项评审(opus)必修项的回归:金额/范围约束的应用层 400 + DB 兜底。"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.category import Category


async def _prep_order_and_sku(client, headers, catalog_headers, db_session):
    """headers：customer/quotation 用（ADMIN 保留 read；customer:manage/quote:manage 不变）。
    catalog_headers：spu/sku 用（catalog:manage，ADMIN 已摘除，须 CATALOG_OPERATOR）。
    """
    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    cust = (await client.post("/api/v1/customers", headers=headers,
            json={"name_i18n": {"zh": "客户A"}})).json()["data"]
    spu_id = (await client.post("/api/v1/spus", headers=catalog_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]
    sku = (await client.post("/api/v1/skus", headers=catalog_headers, json={
        "spu_id": spu_id, "unit": "PCS", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "DN50", "label_i18n": {"zh": "公称通径"}}]})).json()["data"]
    order = (await client.post("/api/v1/quotations", headers=headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    return order, sku


# ── 应用层:干净 400 ──

@pytest.mark.asyncio
async def test_line_rejects_zero_qty(
    client, superadmin_headers, catalog_operator_headers, db_session
):
    order, sku = await _prep_order_and_sku(
        client, superadmin_headers, catalog_operator_headers, db_session)
    r = await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
                          json={"sku_id": sku["id"], "unit_price": 100.0, "qty": 0})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_line_rejects_negative_price(
    client, superadmin_headers, catalog_operator_headers, db_session
):
    order, sku = await _prep_order_and_sku(
        client, superadmin_headers, catalog_operator_headers, db_session)
    r = await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
                          json={"sku_id": sku["id"], "unit_price": -1.0, "qty": 2})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sku_rejects_negative_reference_price(
    client, catalog_operator_headers, db_session
):
    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]
    r = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "PCS", "reference_price": -5, "name_i18n": {"zh": "阀"},
        "spec_items": []})
    assert r.status_code == 422


# ── DB 兜底:绕过应用层直写也被约束挡住 ──

@pytest.mark.asyncio
async def test_db_check_rejects_bad_category_level(db_session):
    db_session.add(Category(code="99", parent_code=None, name_i18n={"zh": "x"},
                            level=0, is_leaf=True, sort_order=0))
    with pytest.raises(IntegrityError):
        await db_session.flush()
