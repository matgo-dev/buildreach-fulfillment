import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.category import Category
from app.db.models.spu import Spu
from app.db.models.sku import Sku


async def _seed(db):
    # unit "ton" 已由 session-scope run_all_seeds()(app/seed.py _UNIT_SEEDS)种下,
    # 复用而非重插 —— 同 tests/test_spu_sku_model_integration.py 惯例,避免 unique 冲突。
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "水泥"},
                    level=1, is_leaf=True, sort_order=0))
    await db.commit()


@pytest.mark.asyncio
async def test_spu_sku_master_fields_persist(db_session):
    await _seed(db_session)
    spu = Spu(spu_code="SPU0001", category_code="10", name_i18n={"zh": "海螺水泥"},
              brand="海螺", description="42.5 普通硅酸盐", hs_code="2523290000", created_by=1)
    db_session.add(spu)
    await db_session.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKU0001", unit="ton", name_i18n={"zh": "海螺42.5 吨装"},
              weight_kg=1000, length_cm=100, width_cm=80, height_cm=120, created_by=1)
    db_session.add(sku)
    await db_session.commit()
    row = (await db_session.execute(select(Sku).where(Sku.id == sku.id))).scalar_one()
    assert row.weight_kg == 1000 and row.height_cm == 120
    srow = (await db_session.execute(select(Spu).where(Spu.id == spu.id))).scalar_one()
    assert srow.brand == "海螺" and srow.hs_code == "2523290000"


@pytest.mark.asyncio
async def test_negative_weight_rejected(db_session):
    await _seed(db_session)
    spu = Spu(spu_code="SPU0002", category_code="10", name_i18n={"zh": "x"}, created_by=1)
    db_session.add(spu)
    await db_session.flush()
    db_session.add(Sku(spu_id=spu.id, sku_code="SKU0002", unit="ton",
                       name_i18n={"zh": "y"}, weight_kg=-1, created_by=1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
