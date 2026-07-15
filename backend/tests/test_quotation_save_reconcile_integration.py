"""T5 整单保存:行 id 对账 + total 维护 + 乐观锁(service 层)。"""
import datetime

import pytest

from app.core.exceptions import QuotationEditConflictError, QuotationNotDraftError
from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.quotation import QuotationStatus
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.services import quotation_service as svc


async def _seed(db):
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()
    spu = Spu(spu_code="SPU9201", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKU9201", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    cust = Customer(code="C900001", name="客户")
    db.add(cust)
    await db.flush()
    return cust, sku


def _ln(sku_id, price, qty, **kw):
    return {"sku_id": sku_id, "unit_price": price, "qty": qty, **kw}


async def _create(db, cust, sku, lines):
    return await svc.save_order(db, order_id=None, customer_id=cust.id, currency="USD",
                                lines=lines, actor_user_id=1, actor_user_email="a@x.com")


@pytest.mark.asyncio
async def test_create_computes_total(db_session):
    cust, sku = await _seed(db_session)
    order = await _create(db_session, cust, sku, [_ln(sku.id, 100, 2), _ln(sku.id, 50, 1)])
    assert str(order.total_amount) == "250.00"
    assert len(await svc.list_lines(db_session, order.id)) == 2


@pytest.mark.asyncio
async def test_put_reconcile_edit_and_delete(db_session):
    cust, sku = await _seed(db_session)
    order = await _create(db_session, cust, sku,
                          [_ln(sku.id, 100, 1), _ln(sku.id, 200, 1), _ln(sku.id, 300, 1)])
    lines = await svc.list_lines(db_session, order.id)
    keep0, keep1 = lines[0], lines[1]   # 删 lines[2]
    updated = await svc.save_order(
        db_session, order_id=order.id, customer_id=cust.id, currency="USD",
        expected_updated_at=order.updated_at,
        lines=[_ln(sku.id, 100, 2, id=keep0.id), _ln(sku.id, 200, 1, id=keep1.id)],
        actor_user_id=1, actor_user_email="a@x.com")
    rows = await svc.list_lines(db_session, updated.id)
    assert {r.id for r in rows} == {keep0.id, keep1.id}   # id 稳定,第三行删除
    assert str(updated.total_amount) == "400.00"          # 100*2 + 200*1


@pytest.mark.asyncio
async def test_put_stale_updated_at_conflict(db_session):
    cust, sku = await _seed(db_session)
    order = await _create(db_session, cust, sku, [_ln(sku.id, 100, 1)])
    with pytest.raises(QuotationEditConflictError):
        await svc.save_order(db_session, order_id=order.id, customer_id=cust.id, currency="USD",
                             expected_updated_at=datetime.datetime(2000, 1, 1),
                             lines=[_ln(sku.id, 100, 1)],
                             actor_user_id=1, actor_user_email="a@x.com")


@pytest.mark.asyncio
async def test_put_non_draft_rejected(db_session):
    cust, sku = await _seed(db_session)
    order = await _create(db_session, cust, sku, [_ln(sku.id, 100, 1)])
    order.status = QuotationStatus.LOCKED
    await db_session.commit()
    with pytest.raises(QuotationNotDraftError):
        await svc.save_order(db_session, order_id=order.id, customer_id=cust.id, currency="USD",
                             expected_updated_at=order.updated_at, lines=[_ln(sku.id, 100, 1)],
                             actor_user_id=1, actor_user_email="a@x.com")
