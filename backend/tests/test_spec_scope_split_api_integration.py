"""SPU/SKU 规格分层(scope 拆分)API 集成:产品级 spec / scope 守卫 / 改分类锁 /
两层搜索(SPU 找商品、SKU 找变体·并集)/ spec_display 并集。"""
import pytest

from app.db.models.category import Category
from app.services import spec_template_service as tmpl

_MAIN_IMG = [{"image_key": "img/x.jpg", "image_type": "MAIN", "sort_order": 0}]


async def _seed_cat_with_attrs(db, code="77"):
    """一个叶子品类:material/standard=产品级(spu),dn=变体轴(sku)。"""
    db.add(Category(code=code, parent_code=None, name_i18n={"zh": "钢管"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()
    await tmpl.upsert_attribute(db, code, key="material", label_i18n={"zh": "材质"},
                                value_type="enum",
                                options=[{"code": "carbon", "label_i18n": {"zh": "碳钢"}}],
                                scope="spu")
    await tmpl.upsert_attribute(db, code, key="standard", label_i18n={"zh": "执行标准"}, scope="spu")
    await tmpl.upsert_attribute(db, code, key="dn", label_i18n={"zh": "公称直径"}, scope="sku")
    await db.commit()


async def _mk_spu(client, headers, *, name="焊接钢管", spec_items=None, code="77"):
    r = await client.post("/api/v1/spus", headers=headers, json={
        "category_code": code, "name_i18n": {"zh": name},
        "spec_items": spec_items or [], "images": _MAIN_IMG})
    return r


@pytest.mark.asyncio
async def test_create_spu_with_product_level_spec(client, product_operator_headers, db_session):
    await _seed_cat_with_attrs(db_session)
    r = await _mk_spu(client, product_operator_headers, spec_items=[
        {"key": "material", "value": "carbon"}, {"key": "standard", "value": "GB/T706"}])
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert {i["key"] for i in data["spec_jsonb"]} == {"material", "standard"}
    disp = {d["key"]: d for d in data["spec_display"]}
    assert disp["material"]["value"] == {"zh": "碳钢"}   # enum→label 解析
    assert disp["material"]["scope"] == "spu"
    assert disp["standard"]["value"] == "GB/T706"        # 标量原样


@pytest.mark.asyncio
async def test_spu_spec_rejects_sku_scope_key(client, product_operator_headers, db_session):
    """产品级(SPU)表单提交一个变体轴(sku)属性 → 400 scope_mismatch。"""
    await _seed_cat_with_attrs(db_session)
    r = await _mk_spu(client, product_operator_headers,
                      spec_items=[{"key": "dn", "value": "DN50"}])
    assert r.status_code == 400, r.text


@pytest.mark.asyncio
async def test_category_locked_when_spec_present(client, product_operator_headers, db_session):
    await _seed_cat_with_attrs(db_session)
    db_session.add(Category(code="88", parent_code=None, name_i18n={"zh": "别的"},
                            level=1, is_leaf=True, sort_order=0))
    await db_session.commit()
    spu_id = (await _mk_spu(client, product_operator_headers,
                            spec_items=[{"key": "material", "value": "carbon"}]
                            )).json()["data"]["id"]
    r = await client.put(f"/api/v1/spus/{spu_id}", headers=product_operator_headers,
                         json={"category_code": "88"})
    assert r.status_code == 409, r.text  # category_locked


@pytest.mark.asyncio
async def test_spu_search_matches_product_attr(client, product_operator_headers, db_session):
    """SPU 维度搜索:按产品级属性 label(碳钢)搜到商品。"""
    await _seed_cat_with_attrs(db_session)
    await _mk_spu(client, product_operator_headers,
                  spec_items=[{"key": "material", "value": "carbon"}])
    r = await client.get("/api/v1/spus?keyword=碳钢", headers=product_operator_headers)
    assert r.status_code == 200
    assert r.json()["data"]["total"] >= 1


@pytest.mark.asyncio
async def test_sku_search_matches_spu_name_and_attr(client, product_operator_headers, db_session):
    """SKU 维度搜索(并集):SKU 自身名不含'焊接钢管',靠继承 SPU 名/产品级属性也能命中。"""
    await _seed_cat_with_attrs(db_session)
    spu_id = (await _mk_spu(client, product_operator_headers, name="焊接钢管",
                            spec_items=[{"key": "material", "value": "carbon"}]
                            )).json()["data"]["id"]
    r_sku = await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "DN50变体"},
        "spec_items": [{"key": "dn", "value": "DN50"}], "images": []})
    assert r_sku.status_code == 200, r_sku.text
    # 按 SPU 名搜(SKU 自身名不含它)
    r1 = await client.get("/api/v1/skus?q=焊接钢管", headers=product_operator_headers)
    assert r1.json()["data"]["total"] >= 1
    # 按产品级属性 label 搜
    r2 = await client.get("/api/v1/skus?q=碳钢", headers=product_operator_headers)
    assert r2.json()["data"]["total"] >= 1
    # 按自身轴值搜
    r3 = await client.get("/api/v1/skus?q=DN50", headers=product_operator_headers)
    assert r3.json()["data"]["total"] >= 1


@pytest.mark.asyncio
async def test_spu_detail_embeds_sku_union_spec_display(client, product_operator_headers, db_session):
    """SPU 详情内嵌 SKU,每个 SKU 的 spec_display = 产品级 ∪ 轴(读时并集)。"""
    await _seed_cat_with_attrs(db_session)
    spu_id = (await _mk_spu(client, product_operator_headers,
                            spec_items=[{"key": "material", "value": "carbon"}]
                            )).json()["data"]["id"]
    await client.post("/api/v1/skus", headers=product_operator_headers, json={
        "spu_id": spu_id, "unit": "piece", "name_i18n": {"zh": "DN50"},
        "spec_items": [{"key": "dn", "value": "DN50"}], "images": []})
    d = (await client.get(f"/api/v1/spus/{spu_id}", headers=product_operator_headers)).json()["data"]
    sku = d["skus"][0]
    keys = {x["key"] for x in sku["spec_display"]}
    assert keys == {"material", "dn"}  # 并集:产品级 material + 轴 dn
    # 产品级在前(排序)
    assert sku["spec_display"][0]["scope"] == "spu"
