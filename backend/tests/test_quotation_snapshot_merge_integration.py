"""T4 两必修:行快照合并 SPU∪SKU 规格 + 写时挡非可选货。"""
import pytest

from app.core.exceptions import QuotationInvalidLineError
from app.db.models.category import Category
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.services import quotation_service


async def _seed(db, *, spu_status="ACTIVE", sku_status="ACTIVE"):
    if not (await db.execute(
            __import__("sqlalchemy").select(Category).where(Category.code == "10")
    )).scalar_one_or_none():
        db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                        level=1, is_leaf=True, sort_order=0))
        await db.flush()
    spu = Spu(spu_code="SPU9101", category_code="10", name_i18n={"zh": "工字钢"}, created_by=1,
              status=spu_status, spec_jsonb=[{"key": "material", "value": "Q235"}])
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKU9101", unit="ton", name_i18n={"zh": "工字钢 200"},
              created_by=1, status=sku_status, spec_jsonb=[{"key": "dn", "value": "DN200"}])
    db.add(sku)
    await db.flush()
    return spu, sku


@pytest.mark.asyncio
async def test_snapshot_merges_spu_and_sku_spec(db_session):
    _, sku = await _seed(db_session)
    name, spec_text, _unit = await quotation_service.compose_line_snapshot(db_session, sku, "zh")
    assert name == "工字钢 200"
    assert "Q235" in spec_text    # 产品级(SPU.spec_jsonb)必须并进来 —— 现状 bug 会缺
    assert "DN200" in spec_text   # 变体轴(SKU.spec_jsonb)


@pytest.mark.asyncio
async def test_assert_sku_available_rejects_inactive_spu(db_session):
    _, sku = await _seed(db_session, spu_status="INACTIVE")
    with pytest.raises(QuotationInvalidLineError):
        await quotation_service.assert_sku_available(db_session, sku.id)


@pytest.mark.asyncio
async def test_assert_sku_available_ok_for_active(db_session):
    _, sku = await _seed(db_session)
    got = await quotation_service.assert_sku_available(db_session, sku.id)
    assert got.id == sku.id
