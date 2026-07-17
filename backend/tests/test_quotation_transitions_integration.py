"""T6 状态跃迁:锁档/解锁/作废 + 转移矩阵门禁(service 层)。"""
import pytest
from sqlalchemy import select

from app.audit.constants import AuditAction
from app.core.exceptions import (
    QuotationCannotUnlockConvertedError,
    QuotationCannotVoidError,
    QuotationEmptyLinesError,
    QuotationInvalidTransitionError,
    QuotationNotDraftError,
)
from app.db.models.audit_log import AuditLog
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
    spu = Spu(spu_code="SPU9301", category_code="10", name_i18n={"zh": "工字钢"},
              created_by=1, status="ACTIVE")
    db.add(spu)
    await db.flush()
    sku = Sku(spu_id=spu.id, sku_code="SKU9301", unit="ton", name_i18n={"zh": "工字钢200"},
              created_by=1, status="ACTIVE")
    db.add(sku)
    cust = Customer(code="C930001", name="客户")
    db.add(cust)
    await db.flush()
    return cust, sku


async def _draft(db, cust, sku, *, with_line=True):
    lines = [{"sku_id": sku.id, "unit_price": 100, "qty": 1}] if with_line else []
    return await svc.save_order(db, order_id=None, customer_id=cust.id, currency="USD",
                                lines=lines, **_ACTOR)


@pytest.mark.asyncio
async def test_lock_empty_draft_rejected(db_session):
    cust, sku = await _seed(db_session)
    order = await _draft(db_session, cust, sku, with_line=False)
    with pytest.raises(QuotationEmptyLinesError):
        await svc.lock_order(db_session, order_id=order.id, **_ACTOR)


@pytest.mark.asyncio
async def test_lock_then_unlock(db_session):
    cust, sku = await _seed(db_session)
    order = await _draft(db_session, cust, sku)
    locked = await svc.lock_order(db_session, order_id=order.id, **_ACTOR)
    assert locked.status == QuotationStatus.LOCKED
    unlocked = await svc.unlock_order(db_session, order_id=order.id, **_ACTOR)
    assert unlocked.status == QuotationStatus.DRAFT


@pytest.mark.asyncio
async def test_void_from_draft_and_locked(db_session):
    cust, sku = await _seed(db_session)
    d = await _draft(db_session, cust, sku)
    assert (await svc.void_order(db_session, order_id=d.id, **_ACTOR)).status == "VOID"
    d2 = await _draft(db_session, cust, sku)
    await svc.lock_order(db_session, order_id=d2.id, **_ACTOR)
    assert (await svc.void_order(db_session, order_id=d2.id, reason="客户取消", **_ACTOR)).status == "VOID"


@pytest.mark.asyncio
async def test_lock_voided_is_invalid_transition(db_session):
    # lock 端点显式仅 DRAFT(SO 取消增量 B1 收紧):非草稿一律 41401,先于矩阵判定。
    cust, sku = await _seed(db_session)
    order = await _draft(db_session, cust, sku)
    await svc.void_order(db_session, order_id=order.id, **_ACTOR)
    with pytest.raises(QuotationNotDraftError):
        await svc.lock_order(db_session, order_id=order.id, **_ACTOR)


@pytest.mark.asyncio
async def test_void_converted_rejected(db_session):
    # 已转销售(终态)作废 → 专有 QuotationCannotVoidError,而非通用「非法转移」。
    cust, sku = await _seed(db_session)
    order = await _draft(db_session, cust, sku)
    order.status = QuotationStatus.CONVERTED
    await db_session.commit()
    with pytest.raises(QuotationCannotVoidError):
        await svc.void_order(db_session, order_id=order.id, **_ACTOR)


@pytest.mark.asyncio
async def test_void_already_void_rejected(db_session):
    # 已作废再作废 → 同样专有 QuotationCannotVoidError(幂等边界,精确报错)。
    cust, sku = await _seed(db_session)
    order = await _draft(db_session, cust, sku)
    await svc.void_order(db_session, order_id=order.id, **_ACTOR)
    with pytest.raises(QuotationCannotVoidError):
        await svc.void_order(db_session, order_id=order.id, **_ACTOR)


@pytest.mark.asyncio
async def test_void_reason_lands_in_audit(db_session):
    # 作废原因必须落审计(留痕带业务原因),不能被丢弃。
    cust, sku = await _seed(db_session)
    order = await _draft(db_session, cust, sku)
    await svc.void_order(db_session, order_id=order.id, reason="客户取消", **_ACTOR)
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.VOID))).scalars().all()
    assert len(rows) == 1 and rows[0].extra == {"reason": "客户取消"}


@pytest.mark.asyncio
async def test_void_without_reason_no_extra(db_session):
    # 不填原因 → extra 为 None(不写空壳 {"reason": null})。
    cust, sku = await _seed(db_session)
    order = await _draft(db_session, cust, sku)
    await svc.void_order(db_session, order_id=order.id, **_ACTOR)
    rows = (await db_session.execute(
        select(AuditLog).where(AuditLog.action == AuditAction.VOID))).scalars().all()
    assert len(rows) == 1 and rows[0].extra is None


@pytest.mark.asyncio
async def test_unlock_converted_rejected(db_session):
    cust, sku = await _seed(db_session)
    order = await _draft(db_session, cust, sku)
    order.status = QuotationStatus.CONVERTED
    await db_session.commit()
    with pytest.raises(QuotationCannotUnlockConvertedError):
        await svc.unlock_order(db_session, order_id=order.id, **_ACTOR)
