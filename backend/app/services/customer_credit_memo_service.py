from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, nullslast, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    AccountVoidedCannotAllocateError,
    AllocationCounterpartyMismatchError,
    AllocationCurrencyMismatchError,
    AllocationExceedsAccountError,
    AllocationIdempotencyConflictError,
    AllocationExceedsSourceError,
    AllocationReverseNotFoundError,
    CustomerCreditMemoExceedsSourceAmountError,
    NotFoundError,
    PurchaseReturnSourceInvalidError,
    SourceHasActiveAllocationsError,
    SourceVoidedError,
)
from app.db.models.customer import Customer
from app.db.models.customer_credit_memo import (
    CustomerCreditAllocation,
    CustomerCreditMemo,
    CustomerCreditMemoStatus,
    CustomerCreditMemoType,
)
from app.db.models.inventory_disposition import (
    InventoryDispositionLine,
    InventoryDispositionOrder,
    InventoryDispositionStatus,
)
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.purchase_order import PurchaseOrderLine
from app.db.models.receipt_allocation import AllocationType
from app.db.models.receivable import Receivable
from app.db.models.sales_order import SalesOrder, SalesOrderLine
from app.services.numbering import allocate
from app.services.repo import paginate

_OPEN_MEMO_STATUSES = (
    CustomerCreditMemoStatus.PENDING_APPROVAL,
    CustomerCreditMemoStatus.POSTED,
)
_CENT = Decimal("0.01")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _d(value) -> Decimal:
    return Decimal(str(value))


def _money(qty, unit_price) -> Decimal:
    return (_d(qty) * _d(unit_price)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _memo_remaining(memo: CustomerCreditMemo) -> Decimal:
    return _d(memo.amount) - _d(memo.amount_allocated)


def _receivable_outstanding(receivable: Receivable) -> Decimal:
    return _d(receivable.amount_original) - _d(receivable.amount_allocated)


async def _next_no(db: AsyncSession) -> str:
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.CUSTOMER_CREDIT_MEMO, period)
    return format_code(NumberScope.CUSTOMER_CREDIT_MEMO, seq, period)


async def _assert_no_active_outbound(db: AsyncSession, sales_order_id: int) -> None:
    exists = (await db.execute(
        select(OutboundOrder.id)
        .where(
            OutboundOrder.sales_order_id == sales_order_id,
            OutboundOrder.status != OutboundOrderStatus.CANCELLED,
        )
        .limit(1))).scalar_one_or_none()
    if exists is not None:
        raise PurchaseReturnSourceInvalidError(
            "销售单已形成出库单,不可继续出库前客户余额贷项流程")


async def _open_memo_id_for_disposition(db: AsyncSession, order_id: int) -> int | None:
    return (await db.execute(
        select(CustomerCreditMemo.id)
        .where(
            CustomerCreditMemo.inventory_disposition_order_id == order_id,
            CustomerCreditMemo.status.in_(_OPEN_MEMO_STATUSES),
        )
        .limit(1)
    )).scalar_one_or_none()


async def _source_credit_limit(
    db: AsyncSession,
    inventory_disposition_order_id: int,
    *,
    exclude_memo_id: int | None = None,
) -> Decimal:
    rows = (await db.execute(
        select(InventoryDispositionLine.qty, SalesOrderLine.unit_price)
        .join(PurchaseOrderLine,
              PurchaseOrderLine.id == InventoryDispositionLine.purchase_order_line_id)
        .join(SalesOrderLine,
              SalesOrderLine.id == PurchaseOrderLine.source_sales_order_line_id)
        .where(
            InventoryDispositionLine.inventory_disposition_order_id
            == inventory_disposition_order_id,
        )
    )).all()
    gross = sum((_money(qty, unit_price) for qty, unit_price in rows), Decimal("0.00"))

    conds = [
        CustomerCreditMemo.inventory_disposition_order_id == inventory_disposition_order_id,
        CustomerCreditMemo.status == CustomerCreditMemoStatus.POSTED,
    ]
    if exclude_memo_id is not None:
        conds.append(CustomerCreditMemo.id != exclude_memo_id)
    posted = (await db.execute(
        select(func.coalesce(func.sum(CustomerCreditMemo.amount), 0)).where(*conds)
    )).scalar_one()
    return gross - _d(posted)


async def _assert_amount_within_source_limit(
    db: AsyncSession,
    *,
    inventory_disposition_order_id: int,
    amount: Decimal,
    exclude_memo_id: int | None = None,
) -> Decimal:
    limit = await _source_credit_limit(
        db,
        inventory_disposition_order_id,
        exclude_memo_id=exclude_memo_id,
    )
    if _d(amount) > limit:
        raise CustomerCreditMemoExceedsSourceAmountError(
            f"客户余额贷项单金额超过处置单可贷金额 {limit}")
    return limit


async def get(db: AsyncSession, memo_id: int) -> CustomerCreditMemo:
    memo = (await db.execute(
        select(CustomerCreditMemo).where(CustomerCreditMemo.id == memo_id)
    )).scalar_one_or_none()
    if memo is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    return memo


async def get_by_inventory_disposition(
    db: AsyncSession,
    order_id: int,
) -> CustomerCreditMemo | None:
    return (await db.execute(
        select(CustomerCreditMemo)
        .where(
            CustomerCreditMemo.inventory_disposition_order_id == order_id,
            CustomerCreditMemo.status != CustomerCreditMemoStatus.VOIDED,
        )
        .order_by(CustomerCreditMemo.created_at.desc(), CustomerCreditMemo.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def allocation_history(
    db: AsyncSession,
    memo_id: int,
) -> list[tuple[CustomerCreditAllocation, int, str]]:
    """客户贷方单抵扣历史,附带应收来源出库单号。"""
    return list((await db.execute(
        select(CustomerCreditAllocation, Receivable.outbound_order_id, OutboundOrder.no)
        .join(Receivable, Receivable.id == CustomerCreditAllocation.receivable_id)
        .join(OutboundOrder, OutboundOrder.id == Receivable.outbound_order_id)
        .where(
            CustomerCreditAllocation.customer_credit_memo_id == memo_id,
        )
        .order_by(CustomerCreditAllocation.id)
    )).all())


async def get_detail(db: AsyncSession, memo_id: int) -> dict:
    memo = await get(db, memo_id)
    return {
        "memo": memo,
        "allocations": await allocation_history(db, memo_id),
    }


async def list_memos(
    db: AsyncSession, *,
    status: str | None = None,
    customer_id: int | None = None,
    sales_order_id: int | None = None,
    inventory_disposition_order_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[CustomerCreditMemo], int]:
    if status:
        conds = [CustomerCreditMemo.status == status]
    else:
        conds = [CustomerCreditMemo.status != CustomerCreditMemoStatus.VOIDED]
    if customer_id:
        conds.append(CustomerCreditMemo.customer_id == customer_id)
    if sales_order_id:
        conds.append(CustomerCreditMemo.sales_order_id == sales_order_id)
    if inventory_disposition_order_id:
        conds.append(
            CustomerCreditMemo.inventory_disposition_order_id
            == inventory_disposition_order_id)
    base = select(CustomerCreditMemo).where(*conds).order_by(
        CustomerCreditMemo.created_at.desc(), CustomerCreditMemo.id.desc())
    return await paginate(db, base, page=page, size=size)


async def list_eligible_receivables(
    db: AsyncSession, *,
    memo_id: int,
    q: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[tuple[Receivable, str, str, str]], int]:
    memo = await get(db, memo_id)
    if memo.status != CustomerCreditMemoStatus.POSTED:
        raise PurchaseReturnSourceInvalidError("仅已过账客户余额贷项单可选择未结应收")
    if _memo_remaining(memo) <= 0:
        raise AllocationExceedsSourceError("客户余额贷项单未分配余额不足")

    conds = [
        Receivable.customer_id == memo.customer_id,
        Receivable.currency == memo.currency,
        Receivable.voided_at.is_(None),
        Receivable.amount_outstanding > 0,
    ]
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(OutboundOrder.no.ilike(like) | SalesOrder.no.ilike(like))

    base = (
        select(Receivable, Customer.name, OutboundOrder.no, SalesOrder.no)
        .join(Customer, Customer.id == Receivable.customer_id)
        .join(OutboundOrder, OutboundOrder.id == Receivable.outbound_order_id)
        .join(SalesOrder, SalesOrder.id == Receivable.sales_order_id)
        .where(*conds)
        .order_by(nullslast(Receivable.due_at.asc()), Receivable.created_at.asc(), Receivable.id.asc())
    )
    return await paginate(db, base, page=page, size=size, scalars=False)


async def posted_unallocated_balance(
    db: AsyncSession, *,
    customer_id: int,
    currency: str = "CNY",
) -> Decimal:
    total = (await db.execute(
        select(func.coalesce(func.sum(CustomerCreditMemo.amount_unallocated), 0))
        .where(
            CustomerCreditMemo.customer_id == customer_id,
            CustomerCreditMemo.currency == currency,
            CustomerCreditMemo.status == CustomerCreditMemoStatus.POSTED,
        )
    )).scalar_one()
    return Decimal(str(total))


async def create_memo(
    db: AsyncSession, *,
    inventory_disposition_order_id: int,
    amount: Decimal,
    reason: str | None,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> CustomerCreditMemo:
    source = (await db.execute(
        select(InventoryDispositionOrder.sales_order_id)
        .where(InventoryDispositionOrder.id == inventory_disposition_order_id)
    )).scalar_one_or_none()
    if source is None:
        raise NotFoundError(f"库存处置单不存在: {inventory_disposition_order_id}")

    from app.services import stock_ledger_service
    await stock_ledger_service.lock_sales_orders(db, [source])

    order = (await db.execute(
        select(InventoryDispositionOrder)
        .where(InventoryDispositionOrder.id == inventory_disposition_order_id)
        .with_for_update()
    )).scalar_one_or_none()
    if order is None:
        raise NotFoundError(f"库存处置单不存在: {inventory_disposition_order_id}")
    if order.sales_order_id != source:
        raise PurchaseReturnSourceInvalidError("库存处置单来源销售单已变化,请刷新后重试")
    if order.status not in {
        InventoryDispositionStatus.HELD,
        InventoryDispositionStatus.CLOSED_WITHOUT_RECEIPT,
    }:
        raise PurchaseReturnSourceInvalidError("仅已待处置或关闭未收货库存处置单可提交客户余额贷项单")

    await _assert_no_active_outbound(db, order.sales_order_id)
    if await _open_memo_id_for_disposition(db, order.id) is not None:
        raise PurchaseReturnSourceInvalidError("库存处置单已有待处理或已过账客户余额贷项单")

    sales_order = (await db.execute(
        select(SalesOrder)
        .where(SalesOrder.id == order.sales_order_id)
        .with_for_update()
    )).scalar_one_or_none()
    if sales_order is None:
        raise PurchaseReturnSourceInvalidError("库存处置单关联的销售单不存在")
    customer = (await db.execute(
        select(Customer)
        .where(Customer.id == sales_order.customer_id)
        .with_for_update()
    )).scalar_one_or_none()
    if customer is None:
        raise PurchaseReturnSourceInvalidError("销售单关联的客户不存在")
    source_credit_limit = await _assert_amount_within_source_limit(
        db,
        inventory_disposition_order_id=order.id,
        amount=amount,
    )

    memo = CustomerCreditMemo(
        no=await _next_no(db),
        inventory_disposition_order_id=order.id,
        sales_order_id=sales_order.id,
        customer_id=customer.id,
        currency="CNY",
        memo_type=CustomerCreditMemoType.INVENTORY_DISPOSITION,
        status=CustomerCreditMemoStatus.PENDING_APPROVAL,
        amount=amount,
        amount_allocated=Decimal("0.00"),
        reason=reason,
        created_by=actor_user_id,
    )
    db.add(memo)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_customer_credit_memos_idp_active" in str(exc.orig):
            raise PurchaseReturnSourceInvalidError(
                "库存处置单已有待处理或已过账客户余额贷项单") from exc
        raise

    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_CREDIT_MEMO,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"inventory_disposition_order_id": order.id, "sales_order_id": sales_order.id,
               "customer_id": customer.id, "amount": str(amount), "currency": "CNY",
               "source_credit_limit": str(source_credit_limit)},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo


async def post_memo(
    db: AsyncSession, *,
    memo_id: int,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> CustomerCreditMemo:
    source = (await db.execute(
        select(CustomerCreditMemo.sales_order_id)
        .where(CustomerCreditMemo.id == memo_id)
    )).scalar_one_or_none()
    if source is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    from app.services import stock_ledger_service
    await stock_ledger_service.lock_sales_orders(db, [source])

    memo = (await db.execute(
        select(CustomerCreditMemo).where(CustomerCreditMemo.id == memo_id)
        .with_for_update()
    )).scalar_one_or_none()
    if memo is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    if memo.sales_order_id != source:
        raise PurchaseReturnSourceInvalidError("客户余额贷项单来源销售单已变化,请刷新后重试")
    if memo.status != CustomerCreditMemoStatus.PENDING_APPROVAL:
        raise PurchaseReturnSourceInvalidError("仅待财务审核客户余额贷项单可过账")
    if memo.created_by == actor_user_id:
        raise PurchaseReturnSourceInvalidError("创建人与过账人不可为同一人")
    order = (await db.execute(
        select(InventoryDispositionOrder)
        .where(InventoryDispositionOrder.id == memo.inventory_disposition_order_id)
        .with_for_update()
    )).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnSourceInvalidError("客户余额贷项单关联的库存处置单不存在")
    if order.status not in {
        InventoryDispositionStatus.HELD,
        InventoryDispositionStatus.CLOSED_WITHOUT_RECEIPT,
    }:
        raise PurchaseReturnSourceInvalidError("库存处置单未完成,不可过账客户余额贷项单")
    if order.sales_order_id != memo.sales_order_id:
        raise PurchaseReturnSourceInvalidError("客户余额贷项单与库存处置单销售单不一致")
    await _assert_no_active_outbound(db, memo.sales_order_id)

    customer = (await db.execute(
        select(Customer).where(Customer.id == memo.customer_id).with_for_update()
    )).scalar_one_or_none()
    if customer is None:
        raise PurchaseReturnSourceInvalidError("客户余额贷项单关联的客户不存在")
    source_credit_limit = await _assert_amount_within_source_limit(
        db,
        inventory_disposition_order_id=order.id,
        amount=memo.amount,
        exclude_memo_id=memo.id,
    )

    memo.status = CustomerCreditMemoStatus.POSTED
    memo.posted_at = _utcnow()
    memo.posted_by = actor_user_id
    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_CREDIT_MEMO,
        action=AuditAction.POST, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"inventory_disposition_order_id": order.id, "customer_id": customer.id,
               "amount": str(memo.amount), "currency": memo.currency,
               "source_credit_limit": str(source_credit_limit)},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo


async def reject_memo(
    db: AsyncSession, *,
    memo_id: int,
    reject_reason: str,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> CustomerCreditMemo:
    memo = (await db.execute(
        select(CustomerCreditMemo).where(CustomerCreditMemo.id == memo_id)
        .with_for_update()
    )).scalar_one_or_none()
    if memo is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    if memo.status != CustomerCreditMemoStatus.PENDING_APPROVAL:
        raise PurchaseReturnSourceInvalidError("仅待财务审核客户余额贷项单可驳回")
    memo.status = CustomerCreditMemoStatus.REJECTED
    memo.rejected_at = _utcnow()
    memo.rejected_by = actor_user_id
    memo.reject_reason = reject_reason
    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_CREDIT_MEMO,
        action=AuditAction.REJECT, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"reject_reason": reject_reason},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo


async def resubmit_memo(
    db: AsyncSession, *,
    memo_id: int,
    amount: Decimal,
    reason: str | None,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> CustomerCreditMemo:
    source = (await db.execute(
        select(CustomerCreditMemo.sales_order_id)
        .where(CustomerCreditMemo.id == memo_id)
    )).scalar_one_or_none()
    if source is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    from app.services import stock_ledger_service
    await stock_ledger_service.lock_sales_orders(db, [source])

    old = (await db.execute(
        select(CustomerCreditMemo).where(CustomerCreditMemo.id == memo_id)
        .with_for_update()
    )).scalar_one_or_none()
    if old is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    if old.sales_order_id != source:
        raise PurchaseReturnSourceInvalidError("客户余额贷项单来源销售单已变化,请刷新后重试")
    if old.status != CustomerCreditMemoStatus.REJECTED:
        raise PurchaseReturnSourceInvalidError("仅已驳回客户余额贷项单可重新提交")
    if await _open_memo_id_for_disposition(db, old.inventory_disposition_order_id) is not None:
        raise PurchaseReturnSourceInvalidError("库存处置单已有待处理或已过账客户余额贷项单")

    order = (await db.execute(
        select(InventoryDispositionOrder)
        .where(InventoryDispositionOrder.id == old.inventory_disposition_order_id)
        .with_for_update()
    )).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnSourceInvalidError("客户余额贷项单关联的库存处置单不存在")
    if order.status not in {
        InventoryDispositionStatus.HELD,
        InventoryDispositionStatus.CLOSED_WITHOUT_RECEIPT,
    }:
        raise PurchaseReturnSourceInvalidError("库存处置单未完成,不可重新提交客户余额贷项单")
    if order.sales_order_id != old.sales_order_id:
        raise PurchaseReturnSourceInvalidError("客户余额贷项单与库存处置单销售单不一致")
    await _assert_no_active_outbound(db, old.sales_order_id)
    customer = (await db.execute(
        select(Customer).where(Customer.id == old.customer_id).with_for_update()
    )).scalar_one_or_none()
    if customer is None:
        raise PurchaseReturnSourceInvalidError("客户余额贷项单关联的客户不存在")
    source_credit_limit = await _assert_amount_within_source_limit(
        db,
        inventory_disposition_order_id=order.id,
        amount=amount,
        exclude_memo_id=old.id,
    )

    memo = CustomerCreditMemo(
        no=await _next_no(db),
        inventory_disposition_order_id=old.inventory_disposition_order_id,
        sales_order_id=old.sales_order_id,
        customer_id=old.customer_id,
        currency="CNY",
        memo_type=old.memo_type,
        status=CustomerCreditMemoStatus.PENDING_APPROVAL,
        amount=amount,
        amount_allocated=Decimal("0.00"),
        reason=reason,
        resubmitted_from_id=old.id,
        created_by=actor_user_id,
    )
    db.add(memo)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_customer_credit_memos_idp_active" in str(exc.orig):
            raise PurchaseReturnSourceInvalidError(
                "库存处置单已有待处理或已过账客户余额贷项单") from exc
        raise

    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_CREDIT_MEMO,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"inventory_disposition_order_id": order.id, "customer_id": customer.id,
               "resubmitted_from_customer_credit_memo_id": old.id,
               "rejected_reason": old.reject_reason, "amount": str(amount),
               "currency": "CNY", "source_credit_limit": str(source_credit_limit)},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo


async def _lock_customer(db: AsyncSession, customer_id: int) -> None:
    exists = (await db.execute(
        select(Customer.id).where(Customer.id == customer_id).with_for_update()
    )).scalar_one_or_none()
    if exists is None:
        raise PurchaseReturnSourceInvalidError("客户不存在")


def _assert_memo_allocatable(memo: CustomerCreditMemo) -> None:
    if memo.status == CustomerCreditMemoStatus.VOIDED:
        raise SourceVoidedError("客户余额贷项单已作废,不可抵扣")
    if memo.status != CustomerCreditMemoStatus.POSTED:
        raise PurchaseReturnSourceInvalidError("仅已过账客户余额贷项单可抵扣应收")
    if _memo_remaining(memo) <= 0:
        raise AllocationExceedsSourceError("客户余额贷项单未分配余额不足")


def _assert_receivable_allocatable(memo: CustomerCreditMemo, receivable: Receivable) -> None:
    if receivable.voided_at is not None:
        raise AccountVoidedCannotAllocateError("应收款已作废,不可抵扣")
    if receivable.customer_id != memo.customer_id:
        raise AllocationCounterpartyMismatchError("客户余额贷项单与应收客户不一致")
    if receivable.currency != memo.currency:
        raise AllocationCurrencyMismatchError("客户余额贷项单与应收币种不一致")
    if _receivable_outstanding(receivable) <= 0:
        raise AllocationExceedsAccountError("应收款未结金额不足")


def _assert_required_text(value: str | None, *, field: str) -> str:
    stripped = (value or "").strip()
    if not stripped:
        raise PurchaseReturnSourceInvalidError(f"{field}不能为空")
    return stripped


async def _allocation_by_idempotency_key(
    db: AsyncSession,
    idempotency_key: str,
) -> CustomerCreditAllocation | None:
    return (await db.execute(
        select(CustomerCreditAllocation)
        .where(CustomerCreditAllocation.idempotency_key == idempotency_key)
    )).scalar_one_or_none()


async def _allocation_by_reverse_idempotency_key(
    db: AsyncSession,
    idempotency_key: str,
) -> CustomerCreditAllocation | None:
    return (await db.execute(
        select(CustomerCreditAllocation)
        .where(CustomerCreditAllocation.reverse_idempotency_key == idempotency_key)
    )).scalar_one_or_none()


def _assert_same_idempotent_allocation(
    existing: CustomerCreditAllocation,
    *,
    memo_id: int,
    receivable_id: int,
    amount: Decimal | None,
) -> CustomerCreditAllocation:
    if existing.customer_credit_memo_id != memo_id or existing.receivable_id != receivable_id:
        raise AllocationIdempotencyConflictError()
    if amount is not None and _d(existing.amount) != _d(amount):
        raise AllocationIdempotencyConflictError()
    return existing


def _assert_same_reverse_idempotent_allocation(
    existing: CustomerCreditAllocation,
    *,
    allocation_id: int,
    reverse_reason: str,
) -> CustomerCreditAllocation:
    if existing.id != allocation_id or existing.reverse_reason != reverse_reason:
        raise AllocationIdempotencyConflictError()
    return existing


async def manual_allocate(
    db: AsyncSession, *,
    memo_id: int,
    receivable_id: int,
    amount: Decimal | None,
    idempotency_key: str,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> CustomerCreditAllocation:
    existing = await _allocation_by_idempotency_key(db, idempotency_key)
    if existing is not None:
        return _assert_same_idempotent_allocation(
            existing, memo_id=memo_id, receivable_id=receivable_id, amount=amount)

    snapshot = (await db.execute(
        select(CustomerCreditMemo.customer_id)
        .where(CustomerCreditMemo.id == memo_id)
    )).scalar_one_or_none()
    if snapshot is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    await _lock_customer(db, snapshot)
    existing = await _allocation_by_idempotency_key(db, idempotency_key)
    if existing is not None:
        return _assert_same_idempotent_allocation(
            existing, memo_id=memo_id, receivable_id=receivable_id, amount=amount)

    memo = (await db.execute(
        select(CustomerCreditMemo)
        .where(CustomerCreditMemo.id == memo_id)
        .with_for_update()
    )).scalar_one_or_none()
    if memo is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    _assert_memo_allocatable(memo)

    receivable = (await db.execute(
        select(Receivable)
        .where(Receivable.id == receivable_id)
        .with_for_update()
    )).scalar_one_or_none()
    if receivable is None:
        raise NotFoundError(f"应收款不存在: {receivable_id}")
    _assert_receivable_allocatable(memo, receivable)

    take = min(_memo_remaining(memo), _receivable_outstanding(receivable))
    if amount is not None:
        requested = _d(amount)
        if requested > _memo_remaining(memo):
            raise AllocationExceedsSourceError("客户余额贷项单未分配余额不足")
        if requested > _receivable_outstanding(receivable):
            raise AllocationExceedsAccountError("应收款未结金额不足")
        take = requested
    if take <= 0:
        raise AllocationExceedsSourceError("客户余额贷项单未分配余额不足")

    alloc = CustomerCreditAllocation(
        customer_credit_memo_id=memo.id,
        receivable_id=receivable.id,
        amount=take,
        alloc_type=AllocationType.MANUAL,
        idempotency_key=idempotency_key,
        created_by=actor_user_id,
    )
    db.add(alloc)
    memo.amount_allocated = _d(memo.amount_allocated) + take
    receivable.amount_allocated = _d(receivable.amount_allocated) + take
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_customer_credit_alloc_idempotency" in str(exc.orig):
            existing = await _allocation_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return _assert_same_idempotent_allocation(
                    existing, memo_id=memo_id, receivable_id=receivable_id, amount=amount)
            raise AllocationIdempotencyConflictError() from exc
        raise

    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_CREDIT_MEMO,
        action=AuditAction.ALLOCATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"allocation_id": alloc.id, "receivable_id": receivable.id,
               "amount": str(take), "alloc_type": AllocationType.MANUAL},
        commit=False)
    await db.commit()
    await db.refresh(alloc)
    return alloc


async def auto_allocate_for_receivable(
    db: AsyncSession, *,
    receivable: Receivable,
    actor_user_id: int,
) -> list[CustomerCreditAllocation]:
    """出库确认生成 CNY 应收后,自动消耗客户已过账余额。

    锁序:客户 → 目标应收 → posted 客户贷方单 FIFO(created_at,id)。
    """
    if receivable.currency != "CNY" or _receivable_outstanding(receivable) <= 0:
        return []
    await _lock_customer(db, receivable.customer_id)
    locked_receivable = (await db.execute(
        select(Receivable)
        .where(Receivable.id == receivable.id)
        .with_for_update()
    )).scalar_one_or_none()
    if locked_receivable is None or locked_receivable.voided_at is not None:
        return []

    ids = (await db.execute(
        select(CustomerCreditMemo.id)
        .where(
            CustomerCreditMemo.customer_id == locked_receivable.customer_id,
            CustomerCreditMemo.currency == locked_receivable.currency,
            CustomerCreditMemo.status == CustomerCreditMemoStatus.POSTED,
            CustomerCreditMemo.amount_unallocated > 0,
        )
        .order_by(CustomerCreditMemo.created_at.asc(), CustomerCreditMemo.id.asc())
    )).scalars().all()

    created: list[CustomerCreditAllocation] = []
    for credit_id in ids:
        if _receivable_outstanding(locked_receivable) <= 0:
            break
        memo = (await db.execute(
            select(CustomerCreditMemo)
            .where(CustomerCreditMemo.id == credit_id)
            .with_for_update()
        )).scalar_one_or_none()
        if memo is None or memo.status != CustomerCreditMemoStatus.POSTED:
            continue
        if memo.customer_id != locked_receivable.customer_id or memo.currency != locked_receivable.currency:
            continue
        if _memo_remaining(memo) <= 0:
            continue
        key = f"auto:{memo.id}:{locked_receivable.id}"
        existing = (await db.execute(
            select(CustomerCreditAllocation.id)
            .where(CustomerCreditAllocation.idempotency_key == key)
            .limit(1)
        )).scalar_one_or_none()
        if existing is not None:
            continue
        take = min(_memo_remaining(memo), _receivable_outstanding(locked_receivable))
        alloc = CustomerCreditAllocation(
            customer_credit_memo_id=memo.id,
            receivable_id=locked_receivable.id,
            amount=take,
            alloc_type=AllocationType.AUTO,
            idempotency_key=key,
            created_by=actor_user_id,
        )
        db.add(alloc)
        memo.amount_allocated = _d(memo.amount_allocated) + take
        locked_receivable.amount_allocated = _d(locked_receivable.amount_allocated) + take
        created.append(alloc)
    await db.flush()
    return created


async def reverse_allocation(
    db: AsyncSession, *,
    allocation_id: int,
    reverse_reason: str,
    idempotency_key: str,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> CustomerCreditAllocation:
    reverse_reason = _assert_required_text(reverse_reason, field="反抵扣原因")
    existing = await _allocation_by_reverse_idempotency_key(db, idempotency_key)
    if existing is not None:
        return _assert_same_reverse_idempotent_allocation(
            existing, allocation_id=allocation_id, reverse_reason=reverse_reason)

    snapshot = (await db.execute(
        select(
            CustomerCreditAllocation.id,
            CustomerCreditAllocation.customer_credit_memo_id,
            CustomerCreditAllocation.receivable_id,
            CustomerCreditAllocation.reversed_at,
            CustomerCreditAllocation.reverse_idempotency_key,
            CustomerCreditAllocation.reverse_reason,
        )
        .where(CustomerCreditAllocation.id == allocation_id)
    )).one_or_none()
    if snapshot is None:
        raise AllocationReverseNotFoundError()
    if snapshot.reversed_at is not None:
        if (snapshot.reverse_idempotency_key == idempotency_key
                and snapshot.reverse_reason == reverse_reason):
            return (await db.execute(
                select(CustomerCreditAllocation)
                .where(CustomerCreditAllocation.id == allocation_id)
            )).scalar_one()
        if snapshot.reverse_idempotency_key is not None:
            raise AllocationReverseNotFoundError("抵扣记录已被其他操作反抵扣")
        raise AllocationReverseNotFoundError()

    memo_snapshot = (await db.execute(
        select(CustomerCreditMemo.customer_id)
        .where(CustomerCreditMemo.id == snapshot.customer_credit_memo_id)
    )).scalar_one()
    await _lock_customer(db, memo_snapshot)
    existing = await _allocation_by_reverse_idempotency_key(db, idempotency_key)
    if existing is not None:
        return _assert_same_reverse_idempotent_allocation(
            existing, allocation_id=allocation_id, reverse_reason=reverse_reason)

    memo = (await db.execute(
        select(CustomerCreditMemo)
        .where(CustomerCreditMemo.id == snapshot.customer_credit_memo_id)
        .with_for_update()
    )).scalar_one()
    receivable = (await db.execute(
        select(Receivable)
        .where(Receivable.id == snapshot.receivable_id)
        .with_for_update()
    )).scalar_one()
    alloc = (await db.execute(
        select(CustomerCreditAllocation)
        .where(CustomerCreditAllocation.id == allocation_id)
        .with_for_update()
    )).scalar_one_or_none()
    if alloc is None:
        raise AllocationReverseNotFoundError()
    if alloc.reversed_at is not None:
        if (alloc.reverse_idempotency_key == idempotency_key
                and alloc.reverse_reason == reverse_reason):
            return alloc
        if alloc.reverse_idempotency_key is not None:
            raise AllocationReverseNotFoundError("抵扣记录已被其他操作反抵扣")
        raise AllocationReverseNotFoundError()

    amt = _d(alloc.amount)
    alloc.reversed_at = _utcnow()
    alloc.reversed_by = actor_user_id
    alloc.reverse_reason = reverse_reason
    alloc.reverse_idempotency_key = idempotency_key
    memo.amount_allocated = _d(memo.amount_allocated) - amt
    receivable.amount_allocated = _d(receivable.amount_allocated) - amt
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_customer_credit_alloc_reverse_idempotency" in str(exc.orig):
            existing = await _allocation_by_reverse_idempotency_key(db, idempotency_key)
            if existing is not None:
                return _assert_same_reverse_idempotent_allocation(
                    existing, allocation_id=allocation_id, reverse_reason=reverse_reason)
            raise AllocationIdempotencyConflictError() from exc
        raise
    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_CREDIT_MEMO,
        action=AuditAction.REVERSE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"allocation_id": alloc.id, "receivable_id": receivable.id,
               "amount": str(amt), "reverse_reason": reverse_reason},
        commit=False)
    await db.commit()
    await db.refresh(alloc)
    return alloc


async def void_memo(
    db: AsyncSession, *,
    memo_id: int,
    void_reason: str,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> CustomerCreditMemo:
    void_reason = _assert_required_text(void_reason, field="作废原因")
    memo = (await db.execute(
        select(CustomerCreditMemo)
        .where(CustomerCreditMemo.id == memo_id)
        .with_for_update()
    )).scalar_one_or_none()
    if memo is None:
        raise NotFoundError(f"客户余额贷项单不存在: {memo_id}")
    if memo.status == CustomerCreditMemoStatus.VOIDED:
        raise SourceVoidedError("客户余额贷项单已作废")
    has_alloc = (await db.execute(
        select(CustomerCreditAllocation.id)
        .where(
            CustomerCreditAllocation.customer_credit_memo_id == memo.id,
            CustomerCreditAllocation.reversed_at.is_(None),
        )
        .limit(1)
    )).scalar_one_or_none()
    if has_alloc is not None:
        raise SourceHasActiveAllocationsError("客户余额贷项单已有抵扣,需先反抵扣再作废")

    memo.status = CustomerCreditMemoStatus.VOIDED
    memo.voided_at = _utcnow()
    memo.voided_by = actor_user_id
    memo.void_reason = void_reason
    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_CREDIT_MEMO,
        action=AuditAction.VOID, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"void_reason": void_reason},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo
