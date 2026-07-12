import pytest


@pytest.mark.asyncio
async def test_create_and_list_customer(client, superadmin_headers):
    r = await client.post("/api/v1/customers", headers=superadmin_headers,
                          json={"name_i18n": {"zh": "东非建材公司"}, "quote_language": "sw"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["code"].startswith("C")
    assert data["name_i18n"] == {"zh": "东非建材公司"}
    assert data["quote_language"] == "sw"

    r2 = await client.get("/api/v1/customers", headers=superadmin_headers)
    assert any(c["id"] == data["id"] for c in r2.json()["data"])


@pytest.mark.asyncio
async def test_create_customer_rejects_missing_zh(client, superadmin_headers):
    r = await client.post("/api/v1/customers", headers=superadmin_headers,
                          json={"name_i18n": {"en": "X"}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_customer_rejects_bad_quote_language(client, superadmin_headers):
    # 报价语言只认 zh/en/sw;BCP47 细码/乱值被应用层挡(422)
    r = await client.post("/api/v1/customers", headers=superadmin_headers,
                          json={"name_i18n": {"zh": "X"}, "quote_language": "sw-TZ"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_customer_requires_permission(client):
    # 无 token → 401
    r = await client.post("/api/v1/customers", json={"name_i18n": {"zh": "X"}})
    assert r.status_code == 401
