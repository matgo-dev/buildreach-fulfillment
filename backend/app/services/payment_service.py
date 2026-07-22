"""付款单服务(付侧实层 + 核销编排)。🔴红线域。登记 / 作废 / 人工核销 / 反核销。

对称 receipt_service,差异:supplier 必填(无 claim / 无 UNCLAIMED)、paid_at(付款日)、
无 D9 门控(payment:read 本身红线,与 payable:read 同域同持有者)。核销走 allocation_engine
(收付泛型,同一套 PAYMENT_SPEC)。登记即触发自动核销(供应商已知,直接冲开口应付)。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    AllocationExceedsAccountError,
    NotFoundError,
    SourceHasActiveAllocationsError,
    SourceVoidedError,
)
from app.db.models.inbound_order import InboundOrder
from app.db.models.payable import Payable
from app.db.models.payment import Payment, PaymentStatus, derive_payment_status
from app.db.models.payment_allocation import PaymentAllocation
from app.db.models.supplier import Supplier
from app.services import allocation_engine
from app.services.allocation_engine import PAYMENT_SPEC
from app.services.numbering import allocate
from app.services.repo import paginate

_STATUS_CONDS = {
    PaymentStatus.FULLY_ALLOCATED: Payment.amount_allocated >= Payment.amount,
    PaymentStatus.UNALLOCATED: Payment.amount_allocated <= 0,
    PaymentStatus.PARTIALLY_ALLOCATED: (Payment.amount_allocated > 0)
    & (Payment.amount_allocated < Payment.amount),
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _period() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


async def get(db: AsyncSession, payment_id: int) -> Payment:
    p = (await db.execute(select(Payment).where(Payment.id == payment_id))).scalar_one_or_none()
    if p is None:
        raise NotFoundError(f"付款单不存在: {payment_id}")
    return p


async def _get_for_update(db: AsyncSession, payment_id: int) -> Payment:
    p = (await db.execute(
        select(Payment).where(Payment.id == payment_id).with_for_update())).scalar_one_or_none()
    if p is None:
        raise NotFoundError(f"付款单不存在: {payment_id}")
    return p


async def _supplier_name(db: AsyncSession, supplier_id: int) -> str | None:
    return (await db.execute(
        select(Supplier.name).where(Supplier.id == supplier_id))).scalar_one_or_none()


async def _allocation_rows(db: AsyncSession, payment_id: int) -> list:
    """活动核销记录 + 应付展示号(入库单号)。付侧无 D9 门控(payment:read 本身红线)。"""
    rows = (await db.execute(
        select(PaymentAllocation, InboundOrder.no)
        .join(Payable, Payable.id == PaymentAllocation.payable_id)
        .join(InboundOrder, InboundOrder.id == Payable.inbound_order_id)
        .where(PaymentAllocation.payment_id == payment_id,
               PaymentAllocation.reversed_at.is_(None))
        .order_by(PaymentAllocation.id))).all()
    return [{
        "id": a.id, "payable_id": a.payable_id, "account_no": inb_no,
        "amount": float(a.amount), "alloc_type": a.alloc_type, "created_at": a.created_at,
    } for a, inb_no in rows]


async def build_detail(db: AsyncSession, payment: Payment) -> dict:
    return {
        "payment": {
            "id": payment.id, "payment_no": payment.payment_no,
            "supplier_id": payment.supplier_id,
            "supplier_display": await _supplier_name(db, payment.supplier_id),
            "account_info": payment.account_info, "currency": payment.currency,
            "amount": float(payment.amount), "amount_allocated": float(payment.amount_allocated),
            "amount_unallocated": float(payment.amount_unallocated),
            "paid_at": payment.paid_at, "note": payment.note,
            "status": derive_payment_status(payment.amount, payment.amount_allocated),
            "voided_at": payment.voided_at, "void_reason": payment.void_reason,
            "created_at": payment.created_at, "updated_at": payment.updated_at,
        },
        "allocations": await _allocation_rows(db, payment.id),
    }


def _audit_allocs(allocs: list[PaymentAllocation]) -> list[dict]:
    return [{"allocation_id": a.id, "payable_id": a.payable_id, "amount": float(a.amount)}
            for a in allocs]


async def register(db: AsyncSession, *, fields: dict, actor_user_id, actor_user_email,
                   request: Request | None = None) -> Payment:
    """登记付款 → 锁 source 行后同事务触发自动核销(冲开口应付,余额留存为预付,P0)。"""
    period = _period()
    seq = await allocate(db, NumberScope.PAYMENT, period)
    payment = Payment(
        payment_no=format_code(NumberScope.PAYMENT, seq, period),
        supplier_id=fields["supplier_id"], account_info=fields.get("account_info"),
        currency=fields["currency"], amount=fields["amount"],
        paid_at=fields["paid_at"], note=fields.get("note"), created_by=actor_user_id)
    db.add(payment)
    await db.flush()
    locked = await allocation_engine.lock_source(db, PAYMENT_SPEC, payment.id)
    allocs = await allocation_engine.auto_allocate(
        db, PAYMENT_SPEC, locked, actor_user_id=actor_user_id)
    await write_audit(db, resource_type=AuditResourceType.PAYMENT, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email, resource_id=payment.id,
                      request=request, extra={"payment_no": payment.payment_no,
                                              "auto_allocations": _audit_allocs(allocs)},
                      commit=False)
    await db.commit()
    await db.refresh(payment)
    return payment


async def void(db: AsyncSession, *, payment_id: int, void_reason: str | None, actor_user_id,
               actor_user_email, request: Request | None = None) -> Payment:
    payment = await _get_for_update(db, payment_id)
    if payment.voided_at is not None:
        raise SourceVoidedError()
    if await allocation_engine.has_active_allocations(db, PAYMENT_SPEC, payment.id):
        raise SourceHasActiveAllocationsError()
    payment.voided_at = _now()
    payment.voided_by = actor_user_id
    payment.void_reason = void_reason
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.PAYMENT, action=AuditAction.VOID,
                      user_id=actor_user_id, user_email=actor_user_email, resource_id=payment.id,
                      request=request, extra={"void_reason": void_reason}, commit=False)
    await db.commit()
    await db.refresh(payment)
    return payment


async def manual_allocate(db: AsyncSession, *, payment_id: int, account_id: int, actor_user_id,
                          actor_user_email, request: Request | None = None) -> Payment:
    """人工核销:选一张应付,金额自动取满 min(未分配, 余额)。已作废 42209;
    跨供应商/币种/超额/作废账 → 引擎抛对应码;偏唯一并发重复 → 42202。"""
    payment = await _get_for_update(db, payment_id)
    if payment.voided_at is not None:
        raise SourceVoidedError()
    try:
        alloc = await allocation_engine.manual_allocate(
            db, PAYMENT_SPEC, payment, account_id, actor_user_id=actor_user_id)
        await write_audit(db, resource_type=AuditResourceType.PAYMENT, action=AuditAction.ALLOCATE,
                          user_id=actor_user_id, user_email=actor_user_email,
                          resource_id=payment.id, request=request,
                          extra={"allocation_id": alloc.id, "payable_id": alloc.payable_id,
                                 "amount": float(alloc.amount), "alloc_type": alloc.alloc_type},
                          commit=False)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_payment_alloc_active" in str(exc.orig):
            raise AllocationExceedsAccountError() from exc
        raise
    await db.refresh(payment)
    return payment


async def reverse_allocation(db: AsyncSession, *, alloc_id: int, reverse_reason: str | None,
                             actor_user_id, actor_user_email,
                             request: Request | None = None) -> Payment:
    alloc, payment, acc = await allocation_engine.reverse(
        db, PAYMENT_SPEC, alloc_id, actor_user_id=actor_user_id, reason=reverse_reason)
    await write_audit(db, resource_type=AuditResourceType.PAYMENT, action=AuditAction.REVERSE,
                      user_id=actor_user_id, user_email=actor_user_email, resource_id=payment.id,
                      request=request, extra={"allocation_id": alloc.id,
                                              "payable_id": alloc.payable_id,
                                              "amount": float(alloc.amount)}, commit=False)
    await db.commit()
    await db.refresh(payment)
    return payment


async def list_payments(db: AsyncSession, *, supplier_id=None, currency: str | None = None,
                        status: str | None = None, q: str | None = None,
                        page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """付款单列表(默认排除作废行):供应商/币种/状态/搜索过滤 + 分页,created_at 降序。
    q = 单号 / 供应商名 模糊。status=VOIDED 显式查作废行。"""
    if status == "VOIDED":
        conds = [Payment.voided_at.isnot(None)]
    else:
        conds = [Payment.voided_at.is_(None)]
        if status in _STATUS_CONDS:
            conds.append(_STATUS_CONDS[status])
    if supplier_id:
        conds.append(Payment.supplier_id == supplier_id)
    if currency:
        conds.append(Payment.currency == currency)
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(Payment.payment_no.ilike(like) | Supplier.name.ilike(like))

    base = (select(Payment, Supplier.name)
            .join(Supplier, Supplier.id == Payment.supplier_id)
            .where(*conds))
    rows, total = await paginate(
        db, base.order_by(Payment.created_at.desc()), page=page, size=size, scalars=False)
    items = [{
        "id": p.id, "payment_no": p.payment_no, "supplier_id": p.supplier_id,
        "supplier_display": sup_name, "currency": p.currency,
        "amount": float(p.amount), "amount_allocated": float(p.amount_allocated),
        "amount_unallocated": float(p.amount_unallocated), "paid_at": p.paid_at,
        "status": derive_payment_status(p.amount, p.amount_allocated),
        "voided_at": p.voided_at, "created_at": p.created_at,
    } for (p, sup_name) in rows]
    return items, total
