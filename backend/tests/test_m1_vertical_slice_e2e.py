import pytest
from decimal import Decimal


@pytest.mark.asyncio
async def test_end_to_end_build_search_quote(
    client, product_operator_headers, sales_headers, db_session
):
    from scripts.import_categories import import_categories
    await import_categories(
        [{"code": "10", "parent_code": None, "name_i18n": {"zh": "阀门"},
          "level": 1, "is_leaf": True, "sort_order": 0}], db_session, dry_run=False)

    cust = (await client.post("/api/v1/customers", headers=sales_headers,
            json={"name": "东非客户", "quote_language": "en"})).json()["data"]
    spu_id = (await client.post("/api/v1/spus", headers=product_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"},
                    "images": [{"image_key": "img/test.jpg", "image_type": "MAIN", "sort_order": 0}]})).json()["data"]["id"]
    sku = (await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "reference_price": 128.0,
        "name_i18n": {"zh": "不锈钢法兰球阀 DN50"},
        "spec_items": [{"key": "dn", "value": "DN50", "label_i18n": {"zh": "公称通径"}},
                       {"key": "material", "value": {"zh": "不锈钢 304"}, "label_i18n": {"zh": "材质"}}]
    })).json()["data"]

    # 搜索是读:SALES 持 product:read
    found = (await client.get("/api/v1/skus?q=法兰球阀", headers=sales_headers)).json()["data"]
    assert any(s["id"] == sku["id"] for s in found["items"])

    # 上架 SPU(报价选料要求 SKU/SPU 均 ACTIVE 可选货)
    act = await client.patch(f"/api/v1/spus/{spu_id}/status", headers=product_operator_headers,
                             json={"status": "ACTIVE"})
    assert act.status_code == 200, act.text

    # 建报价(整单:表头 + 行一次提交;报价须 SALES 角色)
    order = (await client.post("/api/v1/quotations", headers=sales_headers,
             json={"customer_id": cust["id"], "currency": "USD",
                   "lines": [{"sku_id": sku["id"], "unit_price": 150.0, "qty": 2}]})).json()["data"]
    assert order["language"] == "en"
    assert Decimal(str(order["total_amount"])) == Decimal("300.00")   # 150*2
    line = (await client.get(f"/api/v1/quotations/{order['id']}",
            headers=sales_headers)).json()["data"]["lines"][0]
    # unit_snapshot 冻结 units.code("piece"),展示层按**内部界面语言**(zh)翻译成"件";
    # 不随单据语言走(order.language=en 也显示中文),否则中文运营界面单位列会中英混排。
    assert line["unit_snapshot"] == "件"
    assert line["name_snapshot"]  # 非空快照
