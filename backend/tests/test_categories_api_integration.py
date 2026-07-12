import pytest


@pytest.mark.asyncio
async def test_categories_tree_requires_read(client):
    assert (await client.get("/api/v1/categories/tree")).status_code == 401


@pytest.mark.asyncio
async def test_categories_tree_ok(client, superadmin_headers):
    r = await client.get("/api/v1/categories/tree", headers=superadmin_headers)
    assert r.status_code == 200
    assert isinstance(r.json()["data"]["items"], list)


@pytest.mark.asyncio
async def test_spec_suggestions_ok(client, superadmin_headers):
    r = await client.get("/api/v1/categories/10/spec-suggestions", headers=superadmin_headers)
    assert r.status_code in (200, 404)  # 该分类无模板则空/404,均可


@pytest.mark.asyncio
async def test_spec_suggestions_includes_value_type_and_options(
    client, superadmin_headers, db_session
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

    r = await client.get("/api/v1/categories/77/spec-suggestions", headers=superadmin_headers)
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["key"] == "material"
    assert items[0]["value_type"] == "enum"
    assert items[0]["options"] == options
