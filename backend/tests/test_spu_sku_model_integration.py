import pytest
from sqlalchemy import select

from app.db.models.category import Category
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.db.models.user import User


@pytest.mark.asyncio
async def test_spu_sku_persist_with_jsonb(db_session):
    # created_by NOT NULL FK→users:用会话级 seed 种下的引导管理员当创建人
    uid = (await db_session.execute(select(User))).scalars().first().id
    db_session.add(Category(code="10", parent_code=None, name_i18n={"zh": "阀门"},
                            level=1, is_leaf=True, sort_order=0))
    await db_session.flush()
    spu = Spu(spu_code="SPUTEST0001", category_code="10", name_i18n={"zh": "球阀"},
              created_by=uid)
    db_session.add(spu)
    await db_session.flush()
    db_session.add(Sku(spu_id=spu.id, sku_code="SKUTEST00001", unit="piece",
                       reference_price=128.00, spec_jsonb=[{"key": "dn", "value": "DN50"}],
                       search_text="球阀 DN50 SKUTEST00001", name_i18n={"zh": "球阀 DN50"},
                       created_by=uid))
    await db_session.flush()
    row = (await db_session.execute(
        select(Sku).where(Sku.sku_code == "SKUTEST00001"))).scalar_one()
    assert row.spec_jsonb[0]["value"] == "DN50"
    assert float(row.reference_price) == 128.00
