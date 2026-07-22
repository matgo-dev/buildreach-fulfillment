"""收款单服务(收侧实层 + 核销编排)。登记 / 认领 / 作废 / 人工核销 / 反核销。

登记即生效(无草稿态,D11):录入的是已发生的银行事实,已认领则同事务触发自动核销。
纠错 = 作废重录(voided_at 留痕,零活动核销才可作废)。核销走 allocation_engine(收付泛型)。
D9 门控:内嵌应收明细额对无 receivable:read 者脱敏为 null(权限跟数据走)。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    AllocationPairAlreadyActiveError,
    NotFoundError,
    ReceiptNotUnclaimedError,
    SourceHasActiveAllocationsError,
    SourceVoidedError,
)
from app.db.models.customer import Customer
from app.db.models.outbound_order import OutboundOrder
from app.db.models.receipt import Receipt, ReceiptStatus, derive_receipt_status
from app.db.models.receipt_allocation import ReceiptAllocation
from app.db.models.receivable import Receivable
from app.services import allocation_engine
from app.services.allocation_engine import RECEIPT_SPEC
from app.services.numbering import allocate
from app.services.repo import paginate

# 派生状态 → SQL 谓词(镜像 derive_receipt_status 判序;UNCLAIMED 由 customer_id 空判,独立)。
_STATUS_CONDS = {
    ReceiptStatus.UNCLAIMED: Receipt.customer_id.is_(None),
    ReceiptStatus.FULLY_ALLOCATED: Receipt.customer_id.isnot(None)
    & (Receipt.amount_allocated >= Receipt.amount),
    ReceiptStatus.UNALLOCATED: Receipt.customer_id.isnot(None)
    & (Receipt.amount_allocated <= 0),
    ReceiptStatus.PARTIALLY_ALLOCATED: Receipt.customer_id.isnot(None)
    & (Receipt.amount_allocated > 0) & (Receipt.amount_allocated < Receipt.amount),
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _period() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m")


async def get(db: AsyncSession, receipt_id: int) -> Receipt:
    r = (await db.execute(select(Receipt).where(Receipt.id == receipt_id))).scalar_one_or_none()
    if r is None:
        raise NotFoundError(f"收款单不存在: {receipt_id}")
    return r


async def _ensure_customer_exists(db: AsyncSession, customer_id: int) -> None:
    """FK 前置判(公网输入按恶意可达设计):客户不存在 → 404,不裸撞 FK IntegrityError 500。
    只判存在不判状态:停用客户的历史到账仍需登记/认领(钱已到,主数据状态不改变事实)。"""
    ok = (await db.execute(
        select(Customer.id).where(Customer.id == customer_id))).scalar_one_or_none()
    if ok is None:
        raise NotFoundError(f"客户不存在: {customer_id}")


async def _customer_name(db: AsyncSession, customer_id: int | None) -> str | None:
    if customer_id is None:
        return None
    return (await db.execute(
        select(Customer.name).where(Customer.id == customer_id))).scalar_one_or_none()


async def _allocation_rows(db: AsyncSession, receipt_id: int, *, can_read_account: bool) -> list:
    """活动核销记录 + 应收展示号(出库单号,账层无自身业务号)。
    D9:无 receivable:read 者,冲销额(应收侧金额)脱敏为 null,仅见「冲了某张单」。"""
    rows = (await db.execute(
        select(ReceiptAllocation, OutboundOrder.no)
        .join(Receivable, Receivable.id == ReceiptAllocation.receivable_id)
        .join(OutboundOrder, OutboundOrder.id == Receivable.outbound_order_id)
        .where(ReceiptAllocation.receipt_id == receipt_id,
               ReceiptAllocation.reversed_at.is_(None))
        .order_by(ReceiptAllocation.id))).all()
    return [{
        "id": a.id, "receivable_id": a.receivable_id, "account_no": ob_no,
        "amount": (float(a.amount) if can_read_account else None),
        "alloc_type": a.alloc_type, "created_at": a.created_at,
    } for a, ob_no in rows]


async def build_detail(db: AsyncSession, receipt: Receipt, *, can_read_account: bool) -> dict:
    """收款单详情:单头 + 派生状态 + 活动核销记录(应收额按 D9 门控)。"""
    return {
        "receipt": {
            "id": receipt.id, "receipt_no": receipt.receipt_no,
            "customer_id": receipt.customer_id,
            "customer_display": await _customer_name(db, receipt.customer_id),
            "account_info": receipt.account_info, "currency": receipt.currency,
            "amount": float(receipt.amount), "amount_allocated": float(receipt.amount_allocated),
            "amount_unallocated": float(receipt.amount_unallocated),
            "received_at": receipt.received_at, "note": receipt.note,
            "status": derive_receipt_status(receipt.customer_id, receipt.amount,
                                            receipt.amount_allocated),
            "voided_at": receipt.voided_at, "void_reason": receipt.void_reason,
            "created_at": receipt.created_at, "updated_at": receipt.updated_at,
        },
        "allocations": await _allocation_rows(db, receipt.id, can_read_account=can_read_account),
    }


def _audit_allocs(allocs: list[ReceiptAllocation]) -> list[dict]:
    return [{"allocation_id": a.id, "receivable_id": a.receivable_id, "amount": float(a.amount)}
            for a in allocs]


async def register(db: AsyncSession, *, fields: dict, actor_user_id, actor_user_email,
                   request: Request | None = None) -> Receipt:
    """登记收款。已认领(customer_id 非空)→ 锁 source 行后同事务触发自动核销。"""
    if fields.get("customer_id") is not None:
        await _ensure_customer_exists(db, fields["customer_id"])   # 先判再耗号段
    period = _period()
    seq = await allocate(db, NumberScope.RECEIPT, period)
    receipt = Receipt(
        receipt_no=format_code(NumberScope.RECEIPT, seq, period),
        customer_id=fields.get("customer_id"), account_info=fields.get("account_info"),
        currency=fields["currency"], amount=fields["amount"],
        received_at=fields["received_at"], note=fields.get("note"), created_by=actor_user_id)
    db.add(receipt)
    await db.flush()
    allocs: list[ReceiptAllocation] = []
    if receipt.customer_id is not None:
        locked = await allocation_engine.lock_source(db, RECEIPT_SPEC, receipt.id)
        allocs = await allocation_engine.auto_allocate(
            db, RECEIPT_SPEC, locked, actor_user_id=actor_user_id)
    await write_audit(db, resource_type=AuditResourceType.RECEIPT, action=AuditAction.CREATE,
                      user_id=actor_user_id, user_email=actor_user_email, resource_id=receipt.id,
                      request=request, extra={"receipt_no": receipt.receipt_no,
                                              "auto_allocations": _audit_allocs(allocs)},
                      commit=False)
    await db.commit()
    await db.refresh(receipt)
    return receipt


async def _get_for_update(db: AsyncSession, receipt_id: int) -> Receipt:
    r = (await db.execute(
        select(Receipt).where(Receipt.id == receipt_id).with_for_update())).scalar_one_or_none()
    if r is None:
        raise NotFoundError(f"收款单不存在: {receipt_id}")
    return r


async def claim(db: AsyncSession, *, receipt_id: int, customer_id: int, actor_user_id,
                actor_user_email, request: Request | None = None) -> Receipt:
    """认领客户(仅 UNCLAIMED 可认领)→ 回填 customer_id → 同事务触发自动核销。
    已作废 → 42209;已认领 → 42207。"""
    receipt = await _get_for_update(db, receipt_id)
    if receipt.voided_at is not None:
        raise SourceVoidedError()
    if receipt.customer_id is not None:
        raise ReceiptNotUnclaimedError()
    await _ensure_customer_exists(db, customer_id)
    receipt.customer_id = customer_id
    await db.flush()
    allocs = await allocation_engine.auto_allocate(
        db, RECEIPT_SPEC, receipt, actor_user_id=actor_user_id)
    await write_audit(db, resource_type=AuditResourceType.RECEIPT, action=AuditAction.CLAIM,
                      user_id=actor_user_id, user_email=actor_user_email, resource_id=receipt.id,
                      request=request, extra={"customer_id": customer_id,
                                              "auto_allocations": _audit_allocs(allocs)},
                      commit=False)
    await db.commit()
    await db.refresh(receipt)
    return receipt


async def void(db: AsyncSession, *, receipt_id: int, void_reason: str | None, actor_user_id,
               actor_user_email, request: Request | None = None) -> Receipt:
    """作废纠错(D11):零活动核销才可作废(有核销先反核销 → 42208);已作废 → 42209。留痕不硬删。"""
    receipt = await _get_for_update(db, receipt_id)
    if receipt.voided_at is not None:
        raise SourceVoidedError()
    if await allocation_engine.has_active_allocations(db, RECEIPT_SPEC, receipt.id):
        raise SourceHasActiveAllocationsError()
    receipt.voided_at = _now()
    receipt.voided_by = actor_user_id
    receipt.void_reason = void_reason
    await db.flush()
    await write_audit(db, resource_type=AuditResourceType.RECEIPT, action=AuditAction.VOID,
                      user_id=actor_user_id, user_email=actor_user_email, resource_id=receipt.id,
                      request=request, extra={"void_reason": void_reason}, commit=False)
    await db.commit()
    await db.refresh(receipt)
    return receipt


async def manual_allocate(db: AsyncSession, *, receipt_id: int, account_id: int, actor_user_id,
                          actor_user_email, request: Request | None = None) -> Receipt:
    """人工核销:选一张应收,金额自动取满 min(未分配, 余额)(D8)。
    未认领单拒之 42207;已作废 42209;跨客户/币种/超额/作废账/同对已核 → 引擎抛对应码;
    偏唯一兜底并发重复 → 同映射 42210(单线程路径已被引擎前置判接住)。"""
    receipt = await _get_for_update(db, receipt_id)
    if receipt.voided_at is not None:
        raise SourceVoidedError()
    if receipt.customer_id is None:
        raise ReceiptNotUnclaimedError()
    try:
        alloc = await allocation_engine.manual_allocate(
            db, RECEIPT_SPEC, receipt, account_id, actor_user_id=actor_user_id)
        await write_audit(db, resource_type=AuditResourceType.RECEIPT, action=AuditAction.ALLOCATE,
                          user_id=actor_user_id, user_email=actor_user_email,
                          resource_id=receipt.id, request=request,
                          extra={"allocation_id": alloc.id, "receivable_id": alloc.receivable_id,
                                 "amount": float(alloc.amount), "alloc_type": alloc.alloc_type},
                          commit=False)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_receipt_alloc_active" in str(exc.orig):
            raise AllocationPairAlreadyActiveError() from exc
        raise
    await db.refresh(receipt)
    return receipt


async def reverse_allocation(db: AsyncSession, *, alloc_id: int, reverse_reason: str | None,
                             actor_user_id, actor_user_email,
                             request: Request | None = None) -> Receipt:
    """反核销(软删核销记录):金额退回收款未分配 + 应收余额恢复;已反核销/不存在 → 42205。"""
    alloc, receipt, acc = await allocation_engine.reverse(
        db, RECEIPT_SPEC, alloc_id, actor_user_id=actor_user_id, reason=reverse_reason)
    await write_audit(db, resource_type=AuditResourceType.RECEIPT, action=AuditAction.REVERSE,
                      user_id=actor_user_id, user_email=actor_user_email, resource_id=receipt.id,
                      request=request, extra={"allocation_id": alloc.id,
                                              "receivable_id": alloc.receivable_id,
                                              "amount": float(alloc.amount)}, commit=False)
    await db.commit()
    await db.refresh(receipt)
    return receipt


async def list_receipts(db: AsyncSession, *, customer_id=None, currency: str | None = None,
                        status: str | None = None, q: str | None = None,
                        page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """收款单列表(默认排除作废行):客户/币种/状态/搜索过滤 + 分页,created_at 降序。
    q = 单号 / 客户名 模糊。status=VOIDED 显式查作废行。"""
    if status == "VOIDED":
        conds = [Receipt.voided_at.isnot(None)]
    else:
        conds = [Receipt.voided_at.is_(None)]
        if status in _STATUS_CONDS:
            conds.append(_STATUS_CONDS[status])
    if customer_id:
        conds.append(Receipt.customer_id == customer_id)
    if currency:
        conds.append(Receipt.currency == currency)
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(Receipt.receipt_no.ilike(like) | Customer.name.ilike(like))

    base = (select(Receipt, Customer.name)
            .outerjoin(Customer, Customer.id == Receipt.customer_id)
            .where(*conds))
    rows, total = await paginate(
        db, base.order_by(Receipt.created_at.desc()), page=page, size=size, scalars=False)
    items = [{
        "id": r.id, "receipt_no": r.receipt_no, "customer_id": r.customer_id,
        "customer_display": cust_name, "currency": r.currency,
        "amount": float(r.amount), "amount_allocated": float(r.amount_allocated),
        "amount_unallocated": float(r.amount_unallocated), "received_at": r.received_at,
        "status": derive_receipt_status(r.customer_id, r.amount, r.amount_allocated),
        "voided_at": r.voided_at, "created_at": r.created_at,
    } for (r, cust_name) in rows]
    return items, total
