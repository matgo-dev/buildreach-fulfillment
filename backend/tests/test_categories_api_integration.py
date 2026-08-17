import asyncio
from contextlib import suppress

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.exceptions import ConflictError
from app.db.models.category import Category
from app.db.models.spu import Spu
from app.db.models.user import User
from app.services import category_service


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

    r2_1 = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "88.001.001",
        "parent_code": "88.001",
        "name_i18n": {"zh": "测试三级类"},
        "sort_order": 3,
    })
    assert r2_1.status_code == 200, r2_1.text
    assert r2_1.json()["data"]["level"] == 3

    r2_2 = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "88.001.001.001",
        "parent_code": "88.001.001",
        "name_i18n": {"zh": "测试四级类"},
        "sort_order": 4,
    })
    assert r2_2.status_code == 200, r2_2.text
    assert r2_2.json()["data"]["level"] == 4

    direct_specs = await client.get(
        "/api/v1/categories/88.001.001.001/spec-attributes",
        headers=product_readonly_headers,
    )
    assert direct_specs.status_code == 200, direct_specs.text

    suggestions = await client.get(
        "/api/v1/categories/88.001.001.001/spec-suggestions",
        headers=product_readonly_headers,
    )
    assert suggestions.status_code == 200, suggestions.text

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
async def test_create_category_normalizes_and_validates_code(client, product_operator_headers):
    r1 = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": " 90 ",
        "name_i18n": {"zh": "编码归一"},
        "sort_order": 0,
    })
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["code"] == "90"

    r2 = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": " 90.001 ",
        "parent_code": " 90 ",
        "name_i18n": {"zh": "编码归一子类"},
        "sort_order": 0,
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["code"] == "90.001"
    assert r2.json()["data"]["parent_code"] == "90"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    ["foo", ".1", "中文", "01.1", "001", "00", "01.000", "01.001.001.001.001"],
)
async def test_create_category_rejects_invalid_code(client, product_operator_headers, code):
    r = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": code,
        "name_i18n": {"zh": "非法编码"},
        "sort_order": 0,
    })
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_category_rejects_parent_code_mismatch(client, product_operator_headers):
    root = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "91",
        "name_i18n": {"zh": "父级"},
        "sort_order": 0,
    })
    assert root.status_code == 200, root.text

    wrong_root_child = await client.post(
        "/api/v1/categories", headers=product_operator_headers, json={
            "code": "91.001",
            "name_i18n": {"zh": "缺父级"},
            "sort_order": 0,
        })
    assert wrong_root_child.status_code == 400, wrong_root_child.text

    wrong_parent = await client.post(
        "/api/v1/categories", headers=product_operator_headers, json={
            "code": "92.001",
            "parent_code": "91",
            "name_i18n": {"zh": "错父级"},
            "sort_order": 0,
        })
    assert wrong_parent.status_code == 400, wrong_parent.text


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
async def test_create_under_descendant_waits_for_ancestor_deactivation(_engine):
    """新增后代需锁住整条祖先链:祖先停用持锁时,并发新建会等待并在提交后被拒绝。"""
    Session = async_sessionmaker(_engine, expire_on_commit=False)
    async with Session() as setup:
        setup.add(Category(code="93", parent_code=None, name_i18n={"zh": "并发父"},
                           level=1, is_leaf=False, is_active=True, sort_order=0))
        setup.add(Category(code="93.001", parent_code="93", name_i18n={"zh": "并发子"},
                           level=2, is_leaf=True, is_active=True, sort_order=0))
        await setup.commit()

    s1 = Session()
    s2 = Session()
    create_task = None
    try:
        await s1.begin()
        root = (await s1.execute(
            select(Category).where(Category.code == "93").with_for_update()
        )).scalar_one()

        create_task = asyncio.create_task(category_service.create_category(
            s2,
            code="93.001.001",
            parent_code="93.001",
            name_i18n={"zh": "不应漏停"},
            sort_order=0,
            actor_user_id=0,
            actor_user_email="test@test",
        ))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(create_task), timeout=0.2)

        root.is_active = False
        child = (await s1.execute(
            select(Category).where(Category.code == "93.001").with_for_update()
        )).scalar_one()
        child.is_active = False
        await s1.commit()

        with pytest.raises(ConflictError):
            await create_task

        async with Session() as verify:
            created = (await verify.execute(
                select(Category.id).where(Category.code == "93.001.001")
            )).scalar_one_or_none()
            assert created is None
    finally:
        if create_task is not None and not create_task.done():
            create_task.cancel()
            with suppress(asyncio.CancelledError):
                await create_task
        await s1.rollback()
        await s2.rollback()
        await s1.close()
        await s2.close()
        async with Session() as cleanup:
            await cleanup.execute(delete(Category).where(Category.code == "93.001.001"))
            await cleanup.execute(delete(Category).where(Category.code == "93.001"))
            await cleanup.execute(delete(Category).where(Category.code == "93"))
            await cleanup.commit()


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


@pytest.mark.asyncio
async def test_category_spec_attribute_admin_crud(
    client, product_operator_headers, product_readonly_headers
):
    cat = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "94",
        "name_i18n": {"zh": "规格模板类"},
        "sort_order": 0,
    })
    assert cat.status_code == 200, cat.text

    create = await client.post("/api/v1/categories/94/spec-attributes",
                               headers=product_operator_headers, json={
        "label_i18n": {"zh": "材质"},
        "value_type": "enum",
        "options": [{"label_i18n": {"zh": "碳钢"}}],
        "scope": "spu",
        "sort_order": 10,
    })
    assert create.status_code == 200, create.text
    attr = create.json()["data"]
    assert attr["key"].startswith("a_")
    assert attr["scope"] == "spu"
    assert attr["options"][0]["code"].startswith("v_")

    key = attr["key"]
    list_direct = await client.get("/api/v1/categories/94/spec-attributes",
                                   headers=product_readonly_headers)
    assert list_direct.status_code == 200, list_direct.text
    assert [i["key"] for i in list_direct.json()["data"]["items"]] == [key]

    update = await client.put(f"/api/v1/categories/94/spec-attributes/{key}",
                              headers=product_operator_headers, json={
        "label_i18n": {"zh": "材料"},
        "value_type": "enum",
        "options": [
            attr["options"][0],
            {"label_i18n": {"zh": "不锈钢"}},
        ],
        "scope": "spu",
        "unit": "",
        "sort_order": 20,
    })
    assert update.status_code == 200, update.text
    updated = update.json()["data"]
    assert updated["label_i18n"]["zh"] == "材料"
    assert updated["sort_order"] == 20
    assert len(updated["options"]) == 2

    delete = await client.delete(f"/api/v1/categories/94/spec-attributes/{key}",
                                 headers=product_operator_headers)
    assert delete.status_code == 200, delete.text
    after = await client.get("/api/v1/categories/94/spec-attributes",
                             headers=product_readonly_headers)
    assert after.json()["data"]["items"] == []


@pytest.mark.asyncio
async def test_category_spec_attribute_rejects_non_ascii_option_code(
    client, product_operator_headers
):
    cat = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "97",
        "name_i18n": {"zh": "非法选项码类"},
        "sort_order": 0,
    })
    assert cat.status_code == 200, cat.text

    create = await client.post("/api/v1/categories/97/spec-attributes",
                               headers=product_operator_headers, json={
        "label_i18n": {"zh": "材质"},
        "value_type": "enum",
        "options": [{"code": "碳钢", "label_i18n": {"zh": "碳钢"}}],
        "scope": "spu",
    })
    assert create.status_code == 422, create.text


@pytest.mark.asyncio
async def test_category_spec_attribute_requires_product_manage(
    client, product_operator_headers, product_readonly_headers
):
    cat = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "95",
        "name_i18n": {"zh": "权限模板类"},
        "sort_order": 0,
    })
    assert cat.status_code == 200, cat.text

    readonly_create = await client.post("/api/v1/categories/95/spec-attributes",
                                        headers=product_readonly_headers, json={
        "label_i18n": {"zh": "材质"},
        "value_type": "string",
        "scope": "sku",
    })
    assert readonly_create.status_code == 403


@pytest.mark.asyncio
async def test_category_spec_attribute_delete_blocked_when_used(
    client, product_operator_headers, db_session
):
    cat = await client.post("/api/v1/categories", headers=product_operator_headers, json={
        "code": "96",
        "name_i18n": {"zh": "引用模板类"},
        "sort_order": 0,
    })
    assert cat.status_code == 200, cat.text
    create = await client.post("/api/v1/categories/96/spec-attributes",
                               headers=product_operator_headers, json={
        "label_i18n": {"zh": "材质"},
        "value_type": "string",
        "scope": "spu",
    })
    assert create.status_code == 200, create.text
    key = create.json()["data"]["key"]

    user_id = (await db_session.execute(select(User.id).limit(1))).scalar_one()
    db_session.add(Spu(spu_code="SPU-SPEC-USED", category_code="96",
                       name_i18n={"zh": "引用商品"}, spec_jsonb=[{"key": key, "value": "Q235"}],
                       status="DRAFT", created_by=user_id))
    await db_session.commit()

    delete = await client.delete(f"/api/v1/categories/96/spec-attributes/{key}",
                                 headers=product_operator_headers)
    assert delete.status_code == 409, delete.text
