from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import NotFoundError, PurchaseReturnSourceInvalidError
from app.db.models.customer import Customer
from app.db.models.customer_credit_memo import (
    CustomerCreditMemo,
    CustomerCreditMemoStatus,
    CustomerCreditMemoType,
)
from app.db.models.inventory_disposition import (
    InventoryDispositionOrder,
    InventoryDispositionStatus,
)
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.sales_order import SalesOrder
from app.services.numbering import allocate
from app.services.repo import paginate

_OPEN_MEMO_STATUSES = (
    CustomerCreditMemoStatus.PENDING_APPROVAL,
    CustomerCreditMemoStatus.POSTED,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


async def list_memos(
    db: AsyncSession, *,
    status: str | None = None,
    customer_id: int | None = None,
    sales_order_id: int | None = None,
    inventory_disposition_order_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[CustomerCreditMemo], int]:
    conds = [CustomerCreditMemo.status != CustomerCreditMemoStatus.VOIDED]
    if status:
        conds.append(CustomerCreditMemo.status == status)
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
               "customer_id": customer.id, "amount": str(amount), "currency": "CNY"},
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

    memo.status = CustomerCreditMemoStatus.POSTED
    memo.posted_at = _utcnow()
    memo.posted_by = actor_user_id
    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_CREDIT_MEMO,
        action=AuditAction.POST, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"inventory_disposition_order_id": order.id, "customer_id": customer.id,
               "amount": str(memo.amount), "currency": memo.currency},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo


async def reject_memo(
    db: AsyncSession, *,
    memo_id: int,
    reject_reason: str | None,
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

    memo = CustomerCreditMemo(
        no=await _next_no(db),
        inventory_disposition_order_id=old.inventory_disposition_order_id,
        sales_order_id=old.sales_order_id,
        customer_id=old.customer_id,
        currency="CNY",
        memo_type=old.memo_type,
        status=CustomerCreditMemoStatus.PENDING_APPROVAL,
        amount=old.amount,
        amount_allocated=Decimal("0.00"),
        reason=old.reason,
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
               "rejected_reason": old.reject_reason},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo
