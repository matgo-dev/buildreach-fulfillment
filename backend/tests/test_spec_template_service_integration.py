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
    item = await svc.upsert_suggestion_key(
        db_session, "10", key="coating", label_i18n={"zh": "涂层"}, value_type="enum")
    assert item["key"] == "coating"
    assert item["source"] == "运营手加"
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert "coating" in by_key


@pytest.mark.asyncio
async def test_upsert_existing_key_is_noop_keeps_source(db_session):
    await _seed_cat(db_session)
    await svc.upsert_suggestion_key(db_session, "10", key="material",
                                    label_i18n={"zh": "材质"})
    # 再次 upsert 同 key(哪怕 label 不同)不覆盖已有
    await svc.upsert_suggestion_key(db_session, "10", key="material",
                                    label_i18n={"zh": "改过的"})
    by_key = await svc.suggestions_by_key(db_session, "10")
    assert by_key["material"]["label_i18n"] == {"zh": "材质"}
    assert len([s for s in await svc.get_suggestions(db_session, "10")
                if s["key"] == "material"]) == 1


@pytest.mark.asyncio
async def test_upsert_assigns_incrementing_sort_order(db_session):
    await _seed_cat(db_session)
    a = await svc.upsert_suggestion_key(db_session, "10", key="a", label_i18n={"zh": "甲"})
    b = await svc.upsert_suggestion_key(db_session, "10", key="b", label_i18n={"zh": "乙"})
    assert b["sort_order"] > a["sort_order"]
