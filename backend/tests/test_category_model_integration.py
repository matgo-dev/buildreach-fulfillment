import pytest
from sqlalchemy import select

from app.db.models.category import Category


@pytest.mark.asyncio
async def test_category_self_ref_and_jsonb_roundtrip(db_session):
    db_session.add(Category(code="01", parent_code=None, name_i18n={"zh": "建材"},
                            level=1, is_leaf=False, sort_order=10))
    await db_session.flush()
    db_session.add(Category(code="01.001", parent_code="01", name_i18n={"zh": "水泥"},
                            level=2, is_leaf=True, sort_order=10))
    await db_session.flush()
    row = (await db_session.execute(
        select(Category).where(Category.code == "01.001"))).scalar_one()
    assert row.parent_code == "01"
    assert row.name_i18n["zh"] == "水泥"
