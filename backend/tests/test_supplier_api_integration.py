"""供应商主数据 CRUD + 启停 + RBAC。照 customers 档次,补 toggle。"""
import pytest


@pytest.mark.asyncio
async def test_create_and_get_supplier(client, purchaser_headers):
    """建供应商:发号 V000001,默认 ACTIVE。"""
    r = await client.post("/api/v1/suppliers", headers=purchaser_headers, json={
        "name": "钢厂甲", "default_currency": "CNY", "contact_name": "王工",
        "contact_phone": "13800000000"})
    assert r.status_code == 200, r.text
    s = r.json()["data"]
    assert s["code"].startswith("V") and len(s["code"]) == 7
    assert s["status"] == "ACTIVE" and s["default_currency"] == "CNY"

    g = (await client.get(f"/api/v1/suppliers/{s['id']}", headers=purchaser_headers)).json()["data"]
    assert g["name"] == "钢厂甲" and g["contact_name"] == "王工"


@pytest.mark.asyncio
async def test_invalid_currency_rejected(client, purchaser_headers):
    """default_currency 非 ISO4217 三字母大写 → 422(schema 校验)。"""
    r = await client.post("/api/v1/suppliers", headers=purchaser_headers,
                          json={"name": "x", "default_currency": "rmb"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_list_filter_by_status_and_keyword(client, purchaser_headers):
    """列表:状态 tab + 关键词(code/name/联系人)筛选 + 分页。"""
    await client.post("/api/v1/suppliers", headers=purchaser_headers, json={"name": "阿尔法钢铁"})
    b = (await client.post("/api/v1/suppliers", headers=purchaser_headers,
                           json={"name": "贝塔物流"})).json()["data"]
    await client.post(f"/api/v1/suppliers/{b['id']}/deactivate", headers=purchaser_headers)

    active = (await client.get("/api/v1/suppliers?status=ACTIVE", headers=purchaser_headers)).json()["data"]
    assert all(it["status"] == "ACTIVE" for it in active["items"])
    kw = (await client.get("/api/v1/suppliers?q=阿尔法", headers=purchaser_headers)).json()["data"]
    assert kw["total"] >= 1 and any("阿尔法" in it["name"] for it in kw["items"])


@pytest.mark.asyncio
async def test_update_supplier(client, purchaser_headers):
    s = (await client.post("/api/v1/suppliers", headers=purchaser_headers,
                           json={"name": "旧名"})).json()["data"]
    upd = await client.put(f"/api/v1/suppliers/{s['id']}", headers=purchaser_headers,
                           json={"name": "新名", "default_currency": "USD", "address": "深圳"})
    assert upd.status_code == 200
    assert upd.json()["data"]["name"] == "新名" and upd.json()["data"]["address"] == "深圳"


@pytest.mark.asyncio
async def test_toggle_status_idempotent(client, purchaser_headers):
    """启停切换幂等:重复 deactivate 不报错,状态稳定 INACTIVE;再 activate 回 ACTIVE。"""
    s = (await client.post("/api/v1/suppliers", headers=purchaser_headers,
                           json={"name": "切换"})).json()["data"]
    d1 = await client.post(f"/api/v1/suppliers/{s['id']}/deactivate", headers=purchaser_headers)
    d2 = await client.post(f"/api/v1/suppliers/{s['id']}/deactivate", headers=purchaser_headers)
    assert d1.status_code == d2.status_code == 200
    assert d2.json()["data"]["status"] == "INACTIVE"
    a = await client.post(f"/api/v1/suppliers/{s['id']}/activate", headers=purchaser_headers)
    assert a.json()["data"]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_supplier_not_found(client, purchaser_headers):
    r = await client.get("/api/v1/suppliers/999999", headers=purchaser_headers)
    assert r.status_code == 404 and r.json()["code"] == 41501


@pytest.mark.asyncio
async def test_sales_cannot_access_suppliers(client, sales_headers):
    """SALES 无 supplier:*:列表 + 建单均 403(供应商域是采购红线)。"""
    assert (await client.get("/api/v1/suppliers", headers=sales_headers)).status_code == 403
    assert (await client.post("/api/v1/suppliers", headers=sales_headers,
                              json={"name": "x"})).status_code == 403


@pytest.mark.asyncio
async def test_product_operator_cannot_access_suppliers(client, product_operator_headers):
    assert (await client.get("/api/v1/suppliers", headers=product_operator_headers)).status_code == 403
