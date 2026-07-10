import pytest
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.sku import Sku
from app.services import spec_template_service as tmpl


async def _seed_category(db_session, code="10"):
    db_session.add(Category(code=code, parent_code=None, name_i18n={"zh": "阀门"},
                            level=1, is_leaf=True, sort_order=0))
    await db_session.commit()
    # 预置一个已知属性(dn):其余用例走"key 已在模板 → 直接用"分支,
    # 单独测新属性生成键的分支放在 test_create_spu_then_sku_builds_search_text。
    await tmpl.upsert_attribute(db_session, code, key="dn", label_i18n={"zh": "公称通径"})
    await db_session.commit()


@pytest.mark.asyncio
async def test_create_spu_then_sku_builds_search_text(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)

    r_spu = await client.post("/api/v1/spus", headers=catalog_operator_headers,
                              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})
    assert r_spu.status_code == 200, r_spu.text
    spu_id = r_spu.json()["data"]["id"]

    r_sku = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "reference_price": 128.0,
        "name_i18n": {"zh": "不锈钢球阀 DN50"},
        "spec_items": [
            {"key": "dn", "value": "DN50"},
            # 新属性:无 key(或未知 key)+ label_i18n → 后端生成稳定键,绝不拿"coating"
            # 这类用户原文直接当 key(身份≠展示铁律)。
            {"value": {"zh": "喷塑"}, "label_i18n": {"zh": "涂层"}},
        ],
    })
    assert r_sku.status_code == 200, r_sku.text
    sku_id = r_sku.json()["data"]["id"]
    assert r_sku.json()["data"]["sku_code"].startswith("SKU")

    row = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    for token in ["不锈钢球阀 DN50", "DN50", "喷塑"]:
        assert token in row.search_text

    # 新属性由后端生成独立随机稳定键(a_ + 8 位 base62),绝非用户原文/中文,已即时回写模板(source=operator)
    spec_jsonb = r_sku.json()["data"]["spec_jsonb"]
    new_key = next(i["key"] for i in spec_jsonb if i["key"] != "dn")
    new_key_suffix = new_key.removeprefix("a_")
    assert new_key.startswith("a_") and len(new_key_suffix) == 8 and new_key_suffix.isalnum()
    by_key = await tmpl.suggestions_by_key(db_session, "10")
    assert by_key[new_key]["source"] == "operator"
    assert by_key[new_key]["label_i18n"] == {"zh": "涂层"}


@pytest.mark.asyncio
async def test_update_sku_recomputes_search_text(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]
    sku_id = (await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "DN50"}]})).json()["data"]["id"]

    r = await client.put(f"/api/v1/skus/{sku_id}", headers=catalog_operator_headers, json={
        "name_i18n": {"zh": "阀", "en": "Ball Valve XYZ"},
        "spec_items": [{"key": "dn", "value": "DN80"}]})
    assert r.status_code == 200, r.text
    row = (await db_session.execute(select(Sku).where(Sku.id == sku_id))).scalar_one()
    assert "Ball Valve XYZ" in row.search_text and "DN80" in row.search_text
    assert "DN50" not in row.search_text


@pytest.mark.asyncio
async def test_create_sku_rejects_duplicate_spec_key(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]
    r = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "1"}, {"key": "dn", "value": "2"}]})
    assert r.status_code == 400  # SpecContractError


@pytest.mark.asyncio
async def test_update_sku_rejects_name_without_zh(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]
    sku_id = (await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "DN50"}]})).json()["data"]["id"]
    # 改 SKU 名成无 zh → 422(zh 必填铁律,更新路径也守)
    r = await client.put(f"/api/v1/skus/{sku_id}", headers=catalog_operator_headers,
                         json={"name_i18n": {"en": "no zh"}})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_sku_rejects_enum_value_not_in_options(client, catalog_operator_headers, db_session):
    """enum 属性运行期守卫:SKU 填的 value 必须 ∈ 模板 options 的 code 集,否则 400(SpecContractError)。"""
    await _seed_category(db_session)
    options = [{"code": "carbon_steel", "label_i18n": {"zh": "碳钢"}}]
    await tmpl.upsert_attribute(db_session, "10", key="material", label_i18n={"zh": "材质"},
                                value_type="enum", options=options)
    await db_session.commit()

    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]

    # 负例:value 不在 options code 集内 → 400
    r_bad = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "material", "value": "titanium"}]})
    assert r_bad.status_code == 400, r_bad.text

    # 正例对照:value 在 options code 集内 → 成功
    r_ok = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "material", "value": "carbon_steel"}]})
    assert r_ok.status_code == 200, r_ok.text


@pytest.mark.asyncio
async def test_handwritten_key_label_without_zh_rejected(client, catalog_operator_headers, db_session):
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]
    # 手输新 key 但 label_i18n 无 zh → 400,不得污染模板(模板 label 也守 zh 必填)
    r = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "coating", "value": "x", "label_i18n": {"en": "Coating"}}]})
    assert r.status_code == 400


# ── spec §11 Part B:规格计量单位归位 ──

@pytest.mark.asyncio
async def test_inline_new_attribute_unit_lands_in_template_not_spec_jsonb(
    client, catalog_operator_headers, db_session
):
    """新增属性(inline,带 label_i18n)顺手给的 unit 是模板元数据:落进该属性模板行的
    unit 列(如新增"长度"给 unit=mm),但 SKU 自己的 spec_jsonb 只存 {key, value},
    永不落 unit(spec §11 Part B:计量单位只住模板)。"""
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]
    r = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [
            {"value": "50", "label_i18n": {"zh": "长度"}, "unit": "mm"},
        ],
    })
    assert r.status_code == 200, r.text
    spec_jsonb = r.json()["data"]["spec_jsonb"]
    assert len(spec_jsonb) == 1
    assert set(spec_jsonb[0].keys()) == {"key", "value"}  # 无 unit

    new_key = spec_jsonb[0]["key"]
    by_key = await tmpl.suggestions_by_key(db_session, "10")
    assert by_key[new_key]["unit"] == "mm"  # 单位落进模板行


@pytest.mark.asyncio
async def test_existing_key_submitted_unit_is_ignored(client, catalog_operator_headers, db_session):
    """已存在的 key(dn,模板 unit 本为空串)提交 unit 一律忽略——不接受某个 SKU 单独
    覆盖模板计量单位;spec_jsonb 不落 unit,模板行 unit 也不被 SKU 提交值污染。"""
    await _seed_category(db_session)
    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]
    r = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "dn", "value": "DN50", "unit": "inch"}],
    })
    assert r.status_code == 200, r.text
    spec_jsonb = r.json()["data"]["spec_jsonb"]
    assert spec_jsonb == [{"key": "dn", "value": "DN50"}]

    by_key = await tmpl.suggestions_by_key(db_session, "10")
    assert by_key["dn"]["unit"] == ""  # 未被 SKU 提交的 unit=inch 污染


# ── Task 14: inline 新增 enum 选项值(现有 enum 属性缺值时,行锁追加 options) ──

@pytest.mark.asyncio
async def test_create_sku_with_new_enum_option_appends_and_uses_new_code(
    client, catalog_operator_headers, db_session
):
    """enum 属性 value 的 code 不在模板 options 内、但带 label_i18n → 视为 inline
    新增选项:后端生成 v_ 前缀新 code、追加进模板 options,SKU spec_jsonb 落库用该
    新 code(与"新增属性"同构的逃生口,spec §10/§11)。"""
    await _seed_category(db_session)
    options = [{"code": "carbon_steel", "label_i18n": {"zh": "碳钢"}}]
    await tmpl.upsert_attribute(db_session, "10", key="material", label_i18n={"zh": "材质"},
                                value_type="enum", options=options)
    await db_session.commit()

    spu_id = (await client.post("/api/v1/spus", headers=catalog_operator_headers,
              json={"category_code": "10", "name_i18n": {"zh": "球阀"}, "main_image": "img/test.jpg"})).json()["data"]["id"]

    r = await client.post("/api/v1/skus", headers=catalog_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "阀"},
        "spec_items": [{"key": "material", "label_i18n": {"zh": "铝合金"}}]})
    assert r.status_code == 200, r.text

    spec_jsonb = r.json()["data"]["spec_jsonb"]
    assert len(spec_jsonb) == 1
    new_code = spec_jsonb[0]["value"]
    assert spec_jsonb[0]["key"] == "material"
    assert isinstance(new_code, str) and new_code.startswith("v_")
    suffix = new_code.removeprefix("v_")
    assert len(suffix) == 8 and suffix.isalnum()

    by_key = await tmpl.suggestions_by_key(db_session, "10")
    material_options = by_key["material"]["options"]
    assert {"code": "carbon_steel", "label_i18n": {"zh": "碳钢"}} in material_options  # 既有选项原样保留
    assert {"code": new_code, "label_i18n": {"zh": "铝合金"}} in material_options
    assert len(material_options) == 2
