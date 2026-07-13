import pytest
from decimal import Decimal


@pytest.mark.asyncio
async def test_end_to_end_build_search_quote(
    client, superadmin_headers, product_operator_headers, db_session
):
    from scripts.import_categories import import_categories
    await import_categories(
        [{"code": "10", "parent_code": None, "name_i18n": {"zh": "阀门"},
          "level": 1, "is_leaf": True, "sort_order": 0}], db_session, dry_run=False)

    cust = (await client.post("/api/v1/customers", headers=superadmin_headers,
            json={"name_i18n": {"zh": "东非客户"}, "quote_language": "en"})).json()["data"]
    spu_id = (await client.post("/api/v1/spus", headers=product_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"},
                    "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})).json()["data"]["id"]
    sku = (await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "reference_price": 128.0,
        "name_i18n": {"zh": "不锈钢法兰球阀 DN50"},
        "spec_items": [{"key": "dn", "value": "DN50", "label_i18n": {"zh": "公称通径"}},
                       {"key": "material", "value": {"zh": "不锈钢 304"}, "label_i18n": {"zh": "材质"}}]
    })).json()["data"]

    # 搜索是读:ADMIN 有 product:read
    found = (await client.get("/api/v1/skus?q=法兰球阀", headers=superadmin_headers)).json()["data"]
    assert any(s["id"] == sku["id"] for s in found["items"])

    order = (await client.post("/api/v1/quotations", headers=superadmin_headers,
             json={"customer_id": cust["id"], "currency": "USD"})).json()["data"]
    assert order["language"] == "en"
    line = (await client.post(f"/api/v1/quotations/{order['id']}/lines", headers=superadmin_headers,
            json={"sku_id": sku["id"], "unit_price": 150.0, "qty": 2})).json()["data"]
    assert Decimal(str(line["line_total"])) == Decimal("300.00")
    # unit_snapshot 冻结展示 label:order.language=en → units.label_i18n.en("pc"),
    # 而非 sku.unit 的 code("piece")
    assert line["unit_snapshot"] == "pc"
    assert line["name_snapshot"]  # 非空快照
