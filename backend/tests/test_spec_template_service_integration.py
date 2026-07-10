import pytest

from app.db.models.category import Category
from app.services import spec_template_service as svc


async def _seed_cat(db, code="10"):
    db.add(Category(code=code, parent_code=None, name_i18n={"zh": "阀门"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()


@pytest.mark.asyncio
async def test_get_suggestions_empty_when_none(db_session):
    await _seed_cat(db_session)
    assert await svc.get_suggestions(db_session, "10") == []


@pytest.mark.asyncio
async def test_upsert_new_key_writes_operator_source(db_session):
    await _seed_cat(db_session)
    item = await svc.upsert_attribute(
        db_session, "10", key="coating", label_i18n={"zh": "涂层"})
    assert item["key"] == "coating"
    assert item["source"] == "operator"
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert "coating" in by_key


@pytest.mark.asyncio
async def test_upsert_existing_key_is_noop_keeps_source(db_session):
    await _seed_cat(db_session)
    await svc.upsert_attribute(db_session, "10", key="material",
                               label_i18n={"zh": "材质"})
    # 再次 upsert 同 key(哪怕 label 不同)不覆盖已有——DB 层 ON CONFLICT DO NOTHING,
    # 不同 key 的并发 upsert 各自独立插行,不会互相踩踏丢更新(取代旧模型整包数组回写)。
    await svc.upsert_attribute(db_session, "10", key="material",
                               label_i18n={"zh": "改过的"})
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert by_key["material"]["label_i18n"] == {"zh": "材质"}
    assert len([s for s in await svc.get_suggestions(db_session, "10")
                if s["key"] == "material"]) == 1


@pytest.mark.asyncio
async def test_upsert_assigns_incrementing_sort_order(db_session):
    await _seed_cat(db_session)
    a = await svc.upsert_attribute(db_session, "10", key="a", label_i18n={"zh": "甲"})
    b = await svc.upsert_attribute(db_session, "10", key="b", label_i18n={"zh": "乙"})
    assert b["sort_order"] > a["sort_order"]


@pytest.mark.asyncio
async def test_upsert_enum_requires_options(db_session):
    await _seed_cat(db_session)
    with pytest.raises(Exception):
        await svc.upsert_attribute(
            db_session, "10", key="grade", label_i18n={"zh": "等级"}, value_type="enum")


@pytest.mark.asyncio
async def test_upsert_enum_with_options_roundtrips(db_session):
    await _seed_cat(db_session)
    options = [{"code": "hrb400", "label_i18n": {"zh": "HRB400"}}]
    item = await svc.upsert_attribute(
        db_session, "10", key="grade", label_i18n={"zh": "等级"},
        value_type="enum", options=options)
    assert item["options"] == options


@pytest.mark.asyncio
async def test_create_new_attribute_generates_random_ascii_key(db_session):
    """新属性 key 由应用层独立随机生成(a_ + 8 位 base62),绝非中文/用户原文,
    绝非 id/计数派生。两次调用互不相同(唯一性靠 UNIQUE(category_code,key) 兜底,
    极小概率撞键则内部换键重试)。"""
    await _seed_cat(db_session)
    item1 = await svc.create_new_attribute(db_session, "10", label_i18n={"zh": "涂层"})
    item2 = await svc.create_new_attribute(db_session, "10", label_i18n={"zh": "颜色"})
    for item in (item1, item2):
        key = item["key"]
        assert key.startswith("a_")
        suffix = key.removeprefix("a_")
        assert len(suffix) == 8 and suffix.isalnum()
    assert item1["key"] != item2["key"]
    assert item1["source"] == "operator"


@pytest.mark.asyncio
async def test_upsert_different_keys_both_persist_no_lost_update(db_session):
    """两次不同 key 的 upsert(模拟两人各给同类目加一个属性)都要落地——
    取代旧模型"整包数组读出来改一条再整包写回去"导致互相覆盖丢更新的根因。"""
    await _seed_cat(db_session)
    await svc.upsert_attribute(db_session, "10", key="alpha", label_i18n={"zh": "甲属性"})
    await svc.upsert_attribute(db_session, "10", key="beta", label_i18n={"zh": "乙属性"})
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert "alpha" in by_key and "beta" in by_key


# ── Task 14: inline 新增 enum 选项值(行锁追加 options) ──

async def _seed_enum_attr(db, code="10", key="material", options=None):
    await _seed_cat(db, code)
    options = options or [{"code": "carbon_steel", "label_i18n": {"zh": "碳钢"}}]
    await svc.upsert_attribute(db, code, key=key, label_i18n={"zh": "材质"},
                               value_type="enum", options=options)
    return options


@pytest.mark.asyncio
async def test_add_enum_option_generates_v_prefixed_code_and_appends(db_session):
    original_options = await _seed_enum_attr(db_session)
    code = await svc.add_enum_option(db_session, "10", "material", {"zh": "铝合金"})

    assert code.startswith("v_")
    suffix = code.removeprefix("v_")
    assert len(suffix) == 8 and suffix.isalnum()

    by_key = await svc.suggestions_by_key(db_session, "10")
    options = by_key["material"]["options"]
    assert options[0] == original_options[0]  # 既有选项原样保留
    assert {"code": code, "label_i18n": {"zh": "铝合金"}} in options
    assert len(options) == 2


@pytest.mark.asyncio
async def test_add_enum_option_rejects_label_without_zh(db_session):
    await _seed_enum_attr(db_session)
    with pytest.raises(Exception):
        await svc.add_enum_option(db_session, "10", "material", {"en": "Aluminum"})


@pytest.mark.asyncio
async def test_add_enum_option_rejects_non_enum_attribute(db_session):
    await _seed_cat(db_session)
    await svc.upsert_attribute(db_session, "10", key="dn", label_i18n={"zh": "公称通径"})
    with pytest.raises(Exception):
        await svc.add_enum_option(db_session, "10", "dn", {"zh": "新值"})
