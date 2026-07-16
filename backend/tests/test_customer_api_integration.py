import pytest


@pytest.mark.asyncio
async def test_create_and_list_customer(client, superadmin_headers):
    r = await client.post("/api/v1/customers", headers=superadmin_headers,
                          json={"name": "东非建材公司", "quote_language": "sw"})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["code"].startswith("C")
    assert data["name"] == "东非建材公司"
    assert data["quote_language"] == "sw"

    r2 = await client.get("/api/v1/customers", headers=superadmin_headers)
    data2 = r2.json()["data"]
    assert any(c["id"] == data["id"] for c in data2["items"])


@pytest.mark.asyncio
async def test_create_customer_rejects_empty_name(client, superadmin_headers):
    # 客户名=身份单值字段,必填非空(min_length=1)
    r = await client.post("/api/v1/customers", headers=superadmin_headers,
                          json={"name": ""})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_customer_rejects_bad_quote_language(client, superadmin_headers):
    # 报价语言只认 zh/en/sw;BCP47 细码/乱值被应用层挡(422)
    r = await client.post("/api/v1/customers", headers=superadmin_headers,
                          json={"name": "X", "quote_language": "sw-TZ"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_customer_requires_permission(client):
    # 无 token → 401
    r = await client.post("/api/v1/customers", json={"name": "X"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_list_filter_by_status_and_keyword(client, superadmin_headers):
    """列表:状态 tab + 关键词(code/name/联系人)筛选 + 分页信封。"""
    await client.post("/api/v1/customers", headers=superadmin_headers,
                      json={"name": "阿尔法建材", "contact_name": "李工"})
    b = (await client.post("/api/v1/customers", headers=superadmin_headers,
                           json={"name": "贝塔工程"})).json()["data"]
    await client.post(f"/api/v1/customers/{b['id']}/deactivate", headers=superadmin_headers)

    active = (await client.get("/api/v1/customers?status=ACTIVE",
                               headers=superadmin_headers)).json()["data"]
    assert all(it["status"] == "ACTIVE" for it in active["items"])
    kw = (await client.get("/api/v1/customers?q=阿尔法",
                           headers=superadmin_headers)).json()["data"]
    assert kw["total"] >= 1 and any("阿尔法" in it["name"] for it in kw["items"])


@pytest.mark.asyncio
async def test_get_and_update_customer(client, superadmin_headers):
    c = (await client.post("/api/v1/customers", headers=superadmin_headers,
                           json={"name": "旧名", "quote_language": "zh"})).json()["data"]
    g = (await client.get(f"/api/v1/customers/{c['id']}", headers=superadmin_headers)).json()["data"]
    assert g["name"] == "旧名"

    upd = await client.put(f"/api/v1/customers/{c['id']}", headers=superadmin_headers,
                           json={"name": "新名", "quote_language": "en", "address": "达累斯萨拉姆"})
    assert upd.status_code == 200
    d = upd.json()["data"]
    assert d["name"] == "新名" and d["quote_language"] == "en" and d["address"] == "达累斯萨拉姆"
    assert d["code"] == c["code"]  # code 身份键不可变


@pytest.mark.asyncio
async def test_update_rejects_bad_quote_language(client, superadmin_headers):
    c = (await client.post("/api/v1/customers", headers=superadmin_headers,
                           json={"name": "语言校验"})).json()["data"]
    r = await client.put(f"/api/v1/customers/{c['id']}", headers=superadmin_headers,
                         json={"name": "语言校验", "quote_language": "sw-TZ"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_toggle_status_idempotent(client, superadmin_headers):
    """启停切换幂等:重复 deactivate 稳定 INACTIVE;再 activate 回 ACTIVE。"""
    c = (await client.post("/api/v1/customers", headers=superadmin_headers,
                           json={"name": "切换客户"})).json()["data"]
    d1 = await client.post(f"/api/v1/customers/{c['id']}/deactivate", headers=superadmin_headers)
    d2 = await client.post(f"/api/v1/customers/{c['id']}/deactivate", headers=superadmin_headers)
    assert d1.status_code == d2.status_code == 200
    assert d2.json()["data"]["status"] == "INACTIVE"
    a = await client.post(f"/api/v1/customers/{c['id']}/activate", headers=superadmin_headers)
    assert a.json()["data"]["status"] == "ACTIVE"


@pytest.mark.asyncio
async def test_customer_not_found(client, superadmin_headers):
    assert (await client.get("/api/v1/customers/999999",
                             headers=superadmin_headers)).status_code == 404


@pytest.mark.asyncio
async def test_sales_can_manage_customers(client, sales_headers):
    """SALES 持 customer:manage:建/编辑/启停全通(建客户→报价选客户同人同流)。"""
    c = (await client.post("/api/v1/customers", headers=sales_headers,
                           json={"name": "销售自建客户"})).json()["data"]
    assert c["status"] == "ACTIVE"
    upd = await client.put(f"/api/v1/customers/{c['id']}", headers=sales_headers,
                           json={"name": "销售改名"})
    assert upd.status_code == 200
    d = await client.post(f"/api/v1/customers/{c['id']}/deactivate", headers=sales_headers)
    assert d.status_code == 200


@pytest.mark.asyncio
async def test_purchaser_cannot_access_customers(client, purchaser_headers):
    """PURCHASER 无 customer:*:读写均 403(客户域归销售线)。"""
    assert (await client.get("/api/v1/customers",
                             headers=purchaser_headers)).status_code == 403
    assert (await client.post("/api/v1/customers", headers=purchaser_headers,
                              json={"name": "x"})).status_code == 403
