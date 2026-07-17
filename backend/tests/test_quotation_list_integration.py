"""T7 列表查询:筛选/排序/分页 + display 投影(service 层)。"""
from datetime import timedelta

import pytest

from app.db.models.category import Category
from app.db.models.customer import Customer
from app.db.models.quotation import QuotationStatus
from app.db.models.sku import Sku
from app.db.models.spu import Spu
from app.services import quotation_service as svc

_ACTOR = dict(actor_user_id=1, actor_user_email="a@x.com")


async def _seed(db):
    db.add(Category(code="10", parent_code=None, name_i18n={"zh": "钢材"},
                    level=1, is_leaf=True, sort_order=0))
    await db.flush()
    spu = Spu(spu_code="SPU9401", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKU9401", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    cust = Customer(code="C940001", name="客户A")
    db.add(cust)
    await db.flush()
    return cust, sku


async def _mk(db, cust, sku, price):
    return await svc.save_order(db, order_id=None, customer_id=cust.id, currency="USD",
                                lines=[{"sku_id": sku.id, "unit_price": price, "qty": 1}], **_ACTOR)


@pytest.mark.asyncio
async def test_list_filters_by_status(db_session):
    cust, sku = await _seed(db_session)
    o1 = await _mk(db_session, cust, sku, 100)
    await _mk(db_session, cust, sku, 200)
    await svc.lock_order(db_session, order_id=o1.id, **_ACTOR)   # o1 → LOCKED
    drafts, total = await svc.list_orders(db_session, status=QuotationStatus.DRAFT, page=1, size=20)
    assert total == 1 and all(r["status"] == "DRAFT" for r in drafts)


@pytest.mark.asyncio
async def test_list_keyword_pagination_and_sort(db_session):
    cust, sku = await _seed(db_session)
    o1 = await _mk(db_session, cust, sku, 100)
    await _mk(db_session, cust, sku, 300)
    await _mk(db_session, cust, sku, 200)
    # keyword 命中单号
    rows, total = await svc.list_orders(db_session, keyword=o1.no, page=1, size=20)
    assert total == 1 and rows[0]["no"] == o1.no
    # 分页
    page1, total_all = await svc.list_orders(db_session, page=1, size=2)
    assert total_all == 3 and len(page1) == 2
    # total_amount 排序(降序)
    by_amt, _ = await svc.list_orders(db_session, sort="total_amount", page=1, size=20)
    amts = [float(r["total_amount"]) for r in by_amt]
    assert amts == sorted(amts, reverse=True)


@pytest.mark.asyncio
async def test_list_projection_fields(db_session):
    cust, sku = await _seed(db_session)
    await _mk(db_session, cust, sku, 100)
    rows, _ = await svc.list_orders(db_session, salesperson_id=1, page=1, size=20)
    r = rows[0]
    assert r["customer_display"] == "客户A"
    assert r["salesperson_display"]           # users.name 非空
    assert r["line_count"] == 1
    assert {"id", "no", "summary", "currency", "total_amount", "valid_until",
            "created_at"} <= set(r)


@pytest.mark.asyncio
async def test_created_to_includes_same_day(db_session):
    # 回归:created_to 是 date,曾用 <= 会漏掉当天白天创建的报价。半开区间 [.., created_to+1)
    # 应含 created_to 当天;前一天则不含。
    cust, sku = await _seed(db_session)
    o = await _mk(db_session, cust, sku, 100)
    # 边界日从行自身 created_at 派生(UTC,与存储同时钟源)。曾用本地 date.today(),
    # 本地/UTC 跨日时段(如 EDT 晚 8 点后)边界差一天必挂 —— 时钟源要跟数据一致。
    created_day = o.created_at.date()
    rows, total = await svc.list_orders(db_session, created_to=created_day, page=1, size=20)
    assert total == 1 and rows[0]["id"] == o.id
    _, total_yesterday = await svc.list_orders(
        db_session, created_to=created_day - timedelta(days=1), page=1, size=20)
    assert total_yesterday == 0


@pytest.mark.asyncio
async def test_list_salesperson_filter_miss(db_session):
    cust, sku = await _seed(db_session)
    await _mk(db_session, cust, sku, 100)
    _, total = await svc.list_orders(db_session, salesperson_id=99999, page=1, size=20)
    assert total == 0
