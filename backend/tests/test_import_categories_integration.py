import pytest
from sqlalchemy import select

from app.db.models.category import Category
from scripts.import_categories import import_categories

_SAMPLE = [
    {"code": "01", "parent_code": None, "name_i18n": {"zh": "建材", "en": "Materials", "sw": "Vifaa"},
     "level": 1, "is_leaf": False, "sort_order": 10},
    {"code": "01.001", "parent_code": "01", "name_i18n": {"zh": "水泥"},
     "level": 2, "is_leaf": True, "sort_order": 10},
]


@pytest.mark.asyncio
async def test_import_dry_run_writes_nothing(db_session):
    report = await import_categories(_SAMPLE, db_session, dry_run=True)
    assert report["inserted"] == 2
    rows = (await db_session.execute(select(Category))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_import_persists_tree_and_is_idempotent(db_session):
    r1 = await import_categories(_SAMPLE, db_session, dry_run=False)
    assert r1["inserted"] == 2
    # 二次导入:code 已存在 → 跳过,不重复插
    r2 = await import_categories(_SAMPLE, db_session, dry_run=False)
    assert r2["inserted"] == 0 and r2["skipped"] == 2
    child = (await db_session.execute(
        select(Category).where(Category.code == "01.001"))).scalar_one()
    assert child.parent_code == "01"
    assert child.name_i18n == {"zh": "水泥"}


@pytest.mark.asyncio
async def test_import_rejects_missing_zh(db_session):
    bad = [{"code": "99", "parent_code": None, "name_i18n": {"en": "X"},
            "level": 1, "is_leaf": True, "sort_order": 0}]
    report = await import_categories(bad, db_session, dry_run=False)
    assert report["inserted"] == 0
    assert report["errors"]  # 记录 zh 缺失
