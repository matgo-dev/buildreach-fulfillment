"""报价生命周期新列 + status/total CHECK(model → create_all)集成测试。"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.quotation import QuotationLine, QuotationOrder, QuotationStatus
from app.db.models.sku import Sku
from app.db.models.spu import Spu


async def _seed_customer(db) -> Customer:
    c = Customer(code="C000001", name="测试客户")
    db.add(c)
    await db.flush()
    return c


async def _seed_sku(db) -> Sku:
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "水泥"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()
    spu = Spu(spu_code="SPU9001", category_code="10", name_i18n={"zh": "海螺水泥"}, created_by=1)
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKU9001", unit="ton", name_i18n={"zh": "海螺42.5"},
              created_by=1)
    db.add(sku)
    await db.flush()
    return sku


@pytest.mark.asyncio
async def test_order_new_columns_and_locked_status_persist(db_session):
    c = await _seed_customer(db_session)
    order = QuotationOrder(no="Q2026070001", customer_id=c.id, currency="USD",
                           status=QuotationStatus.LOCKED, created_by=1,
                           salesperson_id=1, total_amount=123.45, summary="Q3 钢材报价")
    db_session.add(order)
    await db_session.commit()
    row = (await db_session.execute(
        select(QuotationOrder).where(QuotationOrder.id == order.id))).scalar_one()
    assert row.status == "LOCKED"          # status CHECK 已放开四态
    assert row.salesperson_id == 1
    assert str(row.total_amount) == "123.45"
    assert row.summary == "Q3 钢材报价"


@pytest.mark.asyncio
async def test_negative_total_amount_rejected(db_session):
    c = await _seed_customer(db_session)
    db_session.add(QuotationOrder(no="Q2026070002", customer_id=c.id, currency="USD",
                                  status=QuotationStatus.DRAFT, created_by=1,
                                  salesperson_id=1, total_amount=-1))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_line_remark_persists(db_session):
    c = await _seed_customer(db_session)
    sku = await _seed_sku(db_session)
    order = QuotationOrder(no="Q2026070003", customer_id=c.id, currency="USD",
                           status=QuotationStatus.DRAFT, created_by=1,
                           salesperson_id=1, total_amount=0)
    db_session.add(order)
    await db_session.flush()
    line = QuotationLine(quotation_order_id=order.id, sku_id=sku.id, name_snapshot="海螺42.5",
                         unit_price=100, qty=2, line_total=200, language="zh",
                         remark="需镀锌处理")
    db_session.add(line)
    await db_session.commit()
    row = (await db_session.execute(
        select(QuotationLine).where(QuotationLine.id == line.id))).scalar_one()
    assert row.remark == "需镀锌处理"
