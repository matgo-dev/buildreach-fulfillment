import pytest


@pytest.mark.asyncio
async def test_categories_tree_requires_read(client):
    assert (await client.get("/api/v1/categories/tree")).status_code == 401


@pytest.mark.asyncio
async def test_categories_tree_ok(client, product_readonly_headers):
    r = await client.get("/api/v1/categories/tree", headers=product_readonly_headers)
    assert r.status_code == 200
    assert isinstance(r.json()["data"]["items"], list)


@pytest.mark.asyncio
async def test_product_readonly_cannot_create_category(client, product_readonly_headers):
    r = await client.post("/api/v1/categories", headers=product_readonly_headers, json={
        "code": "88",
        "name_i18n": {"zh": "只读不可写"},
        "sort_order": 0,
    })
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_category_admin_create_update_and_tree_visibility(
    client, product_operator_headers, product_readonly_headers
):
    r1 = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "88",
        "name_i18n": {"zh": "测试大类"},
        "sort_order": 1,
    })
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["level"] == 1
    assert r1.json()["data"]["is_leaf"] is True

    r2 = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "88.001",
        "parent_code": "88",
        "name_i18n": {"zh": "测试子类"},
        "sort_order": 2,
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["level"] == 2

    parent = await client.get("/api/v1/categories/88", headers=product_readonly_headers)
    assert parent.status_code == 200, parent.text
    assert parent.json()["data"]["is_leaf"] is False

    r3 = await client.put("/api/v1/categories/88.001", headers=product_operator_headers, json={
        "name_i18n": {"zh": "测试子类改名", "en": "Subcategory"},
        "sort_order": 3,
    })
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"]["name_i18n"]["zh"] == "测试子类改名"
    assert r3.json()["data"]["sort_order"] == 3

    r4 = await client.post("/api/v1/categories/88/deactivate", headers=product_operator_headers)
    assert r4.status_code == 200, r4.text
    active_tree = await client.get("/api/v1/categories/tree", headers=product_readonly_headers)
    active_codes = {it["code"] for it in active_tree.json()["data"]["items"]}
    assert "88" not in active_codes
    assert "88.001" not in active_codes

    all_tree = await client.get(
        "/api/v1/categories/tree?include_inactive=true", headers=product_readonly_headers)
    all_codes = {it["code"] for it in all_tree.json()["data"]["items"]}
    assert {"88", "88.001"} <= all_codes

    r5 = await client.post("/api/v1/categories/88.001/activate", headers=product_operator_headers)
    assert r5.status_code == 200, r5.text
    active_tree = await client.get("/api/v1/categories/tree", headers=product_readonly_headers)
    active_codes = {it["code"] for it in active_tree.json()["data"]["items"]}
    assert {"88", "88.001"} <= active_codes


@pytest.mark.asyncio
async def test_create_category_rejects_inactive_parent(client, product_operator_headers):
    r1 = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "89",
        "name_i18n": {"zh": "停用父类"},
        "sort_order": 0,
    })
    assert r1.status_code == 200, r1.text
    r2 = await client.post("/api/v1/categories/89/deactivate", headers=product_operator_headers)
    assert r2.status_code == 200, r2.text

    r3 = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "89.001",
        "parent_code": "89",
        "name_i18n": {"zh": "不应创建"},
        "sort_order": 0,
    })
    assert r3.status_code == 409


@pytest.mark.asyncio
async def test_spec_suggestions_ok(client, product_readonly_headers):
    r = await client.get("/api/v1/categories/10/spec-suggestions", headers=product_readonly_headers)
    assert r.status_code in (200, 404)  # 该分类无模板则空/404,均可


@pytest.mark.asyncio
async def test_spec_suggestions_includes_value_type_and_options(
    client, product_readonly_headers, db_session
):
    """路由名不变(仍叫 spec-suggestions),但内部已是 attributes 列表,含 value_type/options。"""
    from app.db.models.category import Category
    from app.services import spec_template_service as tmpl

    db_session.add(Category(code="77", parent_code=None, name_i18n={"zh": "测试分类"},
                            level=1, is_leaf=True, sort_order=0))
    await db_session.commit()
    options = [{"code": "carbon_steel", "label_i18n": {"zh": "碳钢"}}]
    await tmpl.upsert_attribute(db_session, "77", key="material", label_i18n={"zh": "材质"},
                               value_type="enum", options=options)
    await db_session.commit()

    r = await client.get("/api/v1/categories/77/spec-suggestions", headers=product_readonly_headers)
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["key"] == "material"
    assert items[0]["value_type"] == "enum"
    assert items[0]["options"] == options
