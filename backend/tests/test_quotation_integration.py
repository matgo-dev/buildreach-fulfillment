import pytest
from decimal import Decimal
from sqlalchemy import select

from app.db.models.quotation import QuotationLine


async def _prep(client, headers, catalog_headers, db_session, cust_lang=None):
    """headers：customer 用（customer:manage，ADMIN 不变）。
    catalog_headers：spu/sku 用（product:manage，ADMIN 已摘除，须 PRODUCT_OPERATOR）。
    """
    from app.db.models.category import Category
    if not (await db_session.execute(
            select(Category).where(Category.code == "10"))).scalar_one_or_none():
        db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                                level=1, is_leaf=True, sort_order=0))
        await db_session.commit()
    cust = (await client.post("/api/v1/customers", headers=headers,
            json={"name_i18n": {"zh": "客户A"}, "preferred_language": cust_lang})).json()["data"]
    spu_id = (await client.post("/api/v1/spus", headers=catalog_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"},
                    "main_image": "img/test.jpg"})).json()["data"]["id"]
    sku = (await client.post("/api/v1/skus", headers=catalog_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "不锈钢球阀 DN50"},
        "spec_items": [{"key": "dn", "value": "DN50", "label_i18n": {"zh": "公称通径"}}]})).json()["data"]
    return cust, sku


@pytest.mark.asyncio
async def test_draft_language_defaults_from_customer_pref(
    client, superadmin_headers, product_operator_headers, db_session
):
    cust, _ = await _prep(client, superadmin_headers, product_operator_headers, db_session,
                          cust_lang="sw-TZ")
    r = await client.post("/api/v1/quotations", headers=superadmin_headers,
                          json={"customer_id": cust["id"], "currency": "USD"})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["language"] == "sw"   # sw-TZ → sw
    assert r.json()["data"]["no"].startswith("Q")


@pytest.mark.asyncio
async def test_add_line_snapshots_and_computes_total(
    client, superadmin_headers, product_operator_headers, db_session
):
    cust, sku = await _prep(
        client, superadmin_headers, product_operator_headers, db_session)  # 无 pref → language zh
    order = (await client.post("/api/v1/quotations", headers=superadmin_headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    r = await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
                          json={"sku_id": sku["id"], "unit_price": 128.0, "qty": 3})
    assert r.status_code == 200, r.text
    line = r.json()["data"]
    assert line["name_snapshot"] == "不锈钢球阀 DN50"
    assert "DN50" in line["spec_text_snapshot"]
    # unit_snapshot 冻结展示 label(sku.unit="piece" 是 code;order.language=zh 默认
    # → 冻结 units.label_i18n.zh="件",而非 code 本身)
    assert line["unit_snapshot"] == "件"
    assert Decimal(str(line["line_total"])) == Decimal("384.00")  # 128*3


@pytest.mark.asyncio
async def test_snapshot_frozen_after_main_data_change(
    client, superadmin_headers, product_operator_headers, db_session
):
    cust, sku = await _prep(client, superadmin_headers, product_operator_headers, db_session)
    order = (await client.post("/api/v1/quotations", headers=superadmin_headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    line = (await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
            json={"sku_id": sku["id"], "unit_price": 100.0, "qty": 1})).json()["data"]
    # 改 SKU 主数据(SKU 写需 product:manage → PRODUCT_OPERATOR,否则 403 而非真正验证快照冻结)
    r_put = await client.put(f"/api/v1/skus/{sku['id']}", headers=product_operator_headers,
                             json={"name_i18n": {"zh": "改名后的阀"}})
    assert r_put.status_code == 200, r_put.text
    # 报价行快照不变
    row = (await db_session.execute(
        select(QuotationLine).where(QuotationLine.id == line["id"]))).scalar_one()
    assert row.name_snapshot == "不锈钢球阀 DN50"


@pytest.mark.asyncio
async def test_unit_snapshot_freezes_label_not_code(
    client, superadmin_headers, product_operator_headers, db_session
):
    """spec §11 Part A:unit_snapshot 冻结的是 units.label_i18n 展示文字,不存 code、
    无 FK——单位改名后旧报价快照不变(镜像 name_snapshot 的冻结范式)。"""
    from app.db.models.unit import Unit

    cust, sku = await _prep(client, superadmin_headers, product_operator_headers, db_session)
    order = (await client.post("/api/v1/quotations", headers=superadmin_headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    line = (await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
            json={"sku_id": sku["id"], "unit_price": 100.0, "qty": 1})).json()["data"]
    assert line["unit_snapshot"] == "件"
    assert line["unit_snapshot"] != sku["unit"]  # 冻结的是 label,不是 code("piece")

    # 单位改名(如运营把 piece 的 zh 展示名改了)
    unit_row = (await db_session.execute(
        select(Unit).where(Unit.code == "piece"))).scalar_one()
    unit_row.label_i18n = {"zh": "个", "en": "pc"}
    await db_session.commit()

    row = (await db_session.execute(
        select(QuotationLine).where(QuotationLine.id == line["id"]))).scalar_one()
    assert row.unit_snapshot == "件"  # 旧报价快照不变


@pytest.mark.asyncio
async def test_line_snapshot_editable_override(
    client, superadmin_headers, product_operator_headers, db_session
):
    cust, sku = await _prep(client, superadmin_headers, product_operator_headers, db_session)
    order = (await client.post("/api/v1/quotations", headers=superadmin_headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    r = await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
                          json={"sku_id": sku["id"], "unit_price": 100.0, "qty": 1,
                                "name_snapshot": "线下定稿名"})
    assert r.json()["data"]["name_snapshot"] == "线下定稿名"
