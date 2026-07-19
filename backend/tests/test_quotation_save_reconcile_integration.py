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
    """建 3 个不同 SKU(一 SKU 一价公理:同单不许重复 SKU,多行须不同 SKU)。返回 (cust, [sku0,1,2])。"""
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()
    spu = Spu(spu_code="SPU9201", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    skus = []
    for i in range(3):
        sku = Sku(spu_id=spu.id, sku_code=f"SKU920{i}", unit="ton",
                  name_i18n={"zh": f"工字钢20{i}"}, created_by=1, status="ACTIVE")
        db.add(sku)
        skus.append(sku)
    cust = Customer(code="C900001", name="客户")
    db.add(cust)
    await db.flush()
    return cust, skus


def _ln(sku_id, price, qty, **kw):
    return {"sku_id": sku_id, "unit_price": price, "qty": qty, **kw}


async def _create(db, cust, sku, lines):
    return await svc.save_order(db, order_id=None, customer_id=cust.id, currency="USD",
                                lines=lines, actor_user_id=1, actor_user_email="a@x.com")


@pytest.mark.asyncio
async def test_create_computes_total(db_session):
    cust, skus = await _seed(db_session)
    order = await _create(db_session, cust, skus,
                          [_ln(skus[0].id, 100, 2), _ln(skus[1].id, 50, 1)])
    assert str(order.total_amount) == "250.00"
    assert len(await svc.list_lines(db_session, order.id)) == 2


@pytest.mark.asyncio
async def test_put_reconcile_edit_and_delete(db_session):
    cust, skus = await _seed(db_session)
    order = await _create(db_session, cust, skus,
                          [_ln(skus[0].id, 100, 1), _ln(skus[1].id, 200, 1),
                           _ln(skus[2].id, 300, 1)])
    lines = await svc.list_lines(db_session, order.id)
    keep0, keep1 = lines[0], lines[1]   # 删 lines[2]
    updated = await svc.save_order(
        db_session, order_id=order.id, customer_id=cust.id, currency="USD",
        expected_updated_at=order.updated_at,
        lines=[_ln(keep0.sku_id, 100, 2, id=keep0.id), _ln(keep1.sku_id, 200, 1, id=keep1.id)],
        actor_user_id=1, actor_user_email="a@x.com")
    rows = await svc.list_lines(db_session, updated.id)
    assert {r.id for r in rows} == {keep0.id, keep1.id}   # id 稳定,第三行删除
    assert str(updated.total_amount) == "400.00"          # 100*2 + 200*1


@pytest.mark.asyncio
async def test_put_stale_updated_at_conflict(db_session):
    cust, skus = await _seed(db_session)
    order = await _create(db_session, cust, skus, [_ln(skus[0].id, 100, 1)])
    with pytest.raises(QuotationEditConflictError):
        await svc.save_order(db_session, order_id=order.id, customer_id=cust.id, currency="USD",
                             expected_updated_at=datetime.datetime(2000, 1, 1),
                             lines=[_ln(skus[0].id, 100, 1)],
                             actor_user_id=1, actor_user_email="a@x.com")


@pytest.mark.asyncio
async def test_put_non_draft_rejected(db_session):
    cust, skus = await _seed(db_session)
    order = await _create(db_session, cust, skus, [_ln(skus[0].id, 100, 1)])
    order.status = QuotationStatus.LOCKED
    await db_session.commit()
    with pytest.raises(QuotationNotDraftError):
        await svc.save_order(db_session, order_id=order.id, customer_id=cust.id, currency="USD",
                             expected_updated_at=order.updated_at, lines=[_ln(skus[0].id, 100, 1)],
                             actor_user_id=1, actor_user_email="a@x.com")
