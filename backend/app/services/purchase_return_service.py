from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.statemachine import assert_transition
from app.core.exceptions import (
    APCreditMemoExceedsOutstandingError,
    InboundOrderEmptyError,
    InboundOrderInvalidTransitionError,
    InboundOrderNotFoundError,
    NotFoundError,
    PurchaseReturnNotFoundError,
    PurchaseReturnOverQtyError,
    PurchaseReturnSourceInvalidError,
    PurchaseReturnWouldGoNegativeError,
)
from app.db.models.ap_credit_memo import APCreditMemo, APCreditMemoStatus, APCreditMemoType
from app.db.models.company_loss import CompanyLossEntry, CompanyLossEntryStatus
from app.db.models.customer_refund import CustomerRefund, CustomerRefundStatus
from app.db.models.inbound_order import InboundOrder, InboundOrderLine, InboundOrderStatus
from app.db.models.inbound_order import INBOUND_ORDER_TRANSITIONS
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.payable import Payable
from app.db.models.payment import Payment
from app.db.models.payment_allocation import PaymentAllocation
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.db.models.purchase_return import (
    PurchaseReturnKind,
    PurchaseReturnLine,
    PurchaseReturnOrder,
    PurchaseReturnStatus,
)
from app.db.models.sales_order import SalesOrder, SalesOrderLine
from app.db.models.stock import InventoryBalance
from app.services.numbering import allocate
from app.services.repo import paginate
from app.services.stock_ledger_service import StockImpact

_CENT = Decimal("0.01")
_ACTIVE_RETURN_STATUSES = (
    PurchaseReturnStatus.PENDING_APPROVAL,
    PurchaseReturnStatus.APPROVED,
    PurchaseReturnStatus.RETURNED,
    PurchaseReturnStatus.COMPLETED,
)
_OPEN_CREDIT_MEMO_STATUSES = (
    APCreditMemoStatus.PENDING_APPROVAL,
    APCreditMemoStatus.POSTED,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _next_no(db: AsyncSession, scope: NumberScope) -> str:
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, scope, period)
    return format_code(scope, seq, period)


def _money(qty, unit_price) -> Decimal:
    return (Decimal(str(qty)) * Decimal(str(unit_price))).quantize(
        _CENT, rounding=ROUND_HALF_UP)


async def _active_payable_for_update(db: AsyncSession, inbound_order_id: int) -> Payable:
    payable = (await db.execute(
        select(Payable).where(
            Payable.inbound_order_id == inbound_order_id,
            Payable.voided_at.is_(None),
        ).with_for_update())).scalar_one_or_none()
    if payable is None:
        raise PurchaseReturnSourceInvalidError("源入库单没有活动应付,不可创建采购退货")
    return payable


async def _active_payment_ids_for_payable(db: AsyncSession, payable_id: int) -> list[int]:
    rows = (await db.execute(
        select(PaymentAllocation.payment_id)
        .where(
            PaymentAllocation.payable_id == payable_id,
            PaymentAllocation.reversed_at.is_(None),
        ))).scalars().all()
    return sorted(set(rows))


async def _lock_payments_for_update(db: AsyncSession, payment_ids: list[int]) -> dict[int, Payment]:
    locked: dict[int, Payment] = {}
    for payment_id in sorted(set(payment_ids)):
        payment = (await db.execute(
            select(Payment).where(Payment.id == payment_id)
            .with_for_update())).scalar_one_or_none()
        if payment is not None:
            locked[payment.id] = payment
    return locked


async def _active_payable_by_id_for_update(db: AsyncSession, payable_id: int) -> Payable:
    payable = (await db.execute(
        select(Payable).where(
            Payable.id == payable_id,
            Payable.voided_at.is_(None),
        ).with_for_update())).scalar_one_or_none()
    if payable is None:
        raise PurchaseReturnSourceInvalidError("供应商贷项单关联的应付账款不存在或已作废")
    return payable


def _assert_return_kind(order: PurchaseReturnOrder, expected: str, message: str) -> None:
    if order.return_kind != expected:
        raise PurchaseReturnSourceInvalidError(message)


async def _load_line_context(db: AsyncSession, inbound_order_id: int,
                             line_ids: list[int]) -> dict[int, tuple]:
    rows = (await db.execute(
        select(InboundOrderLine, PurchaseOrderLine, SalesOrderLine)
        .join(PurchaseOrderLine, PurchaseOrderLine.id == InboundOrderLine.purchase_order_line_id)
        .join(SalesOrderLine, SalesOrderLine.id == PurchaseOrderLine.source_sales_order_line_id)
        .where(
            InboundOrderLine.inbound_order_id == inbound_order_id,
            InboundOrderLine.id.in_(line_ids),
        ))).all()
    return {iol.id: (iol, pol, sol) for iol, pol, sol in rows}


async def _return_qty_by_inbound_line(
    db: AsyncSession,
    inbound_line_ids: list[int],
    *,
    statuses: tuple[str, ...],
) -> dict[int, Decimal]:
    result = {line_id: Decimal("0") for line_id in inbound_line_ids}
    if not inbound_line_ids:
        return result
    rows = (await db.execute(
        select(
            PurchaseReturnLine.inbound_order_line_id,
            func.coalesce(func.sum(PurchaseReturnLine.qty), 0),
        )
        .join(PurchaseReturnOrder,
              PurchaseReturnOrder.id == PurchaseReturnLine.purchase_return_order_id)
        .where(
            PurchaseReturnLine.inbound_order_line_id.in_(inbound_line_ids),
            PurchaseReturnOrder.status.in_(statuses),
        )
        .group_by(PurchaseReturnLine.inbound_order_line_id))).all()
    for line_id, qty in rows:
        result[line_id] = Decimal(str(qty))
    return result


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
            "销售单已形成出库单,不可走出库前采购退货;请走售后退货退款流程")


async def _assert_no_pending_reverse_order(db: AsyncSession, inbound_order_id: int) -> None:
    exists = (await db.execute(
        select(PurchaseReturnOrder.id)
        .where(
            PurchaseReturnOrder.inbound_order_id == inbound_order_id,
            PurchaseReturnOrder.status.in_({
                PurchaseReturnStatus.PENDING_APPROVAL,
                PurchaseReturnStatus.APPROVED,
            }),
        )
        .limit(1))).scalar_one_or_none()
    if exists is not None:
        raise PurchaseReturnSourceInvalidError("入库单已有待处理逆向单据,请先完成或驳回")


async def _assert_stock_available(db: AsyncSession, impacts: list[StockImpact]) -> None:
    qty_by_key: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0"))
    for impact in impacts:
        qty_by_key[(impact.sales_order_id, impact.sku_id)] += impact.qty

    negatives = []
    for (so_id, sku_id), qty in qty_by_key.items():
        balance = (await db.execute(
            select(InventoryBalance)
            .where(
                InventoryBalance.sales_order_id == so_id,
                InventoryBalance.sku_id == sku_id,
            )
            .with_for_update())).scalar_one_or_none()
        current_available = Decimal(str(balance.available_qty)) if balance else Decimal("0")
        if current_available - qty < 0:
            negatives.append({
                "sales_order_id": so_id,
                "sku_id": sku_id,
                "available_qty": float(current_available),
                "return_qty": float(qty),
            })
    if negatives:
        raise PurchaseReturnWouldGoNegativeError(data={"items": negatives})


def _build_line_payloads(lines: list[dict], contexts: dict[int, tuple],
                         active_return_qty: dict[int, Decimal]) -> tuple[list[dict], Decimal]:
    payloads: list[dict] = []
    total = Decimal("0")
    seen: set[int] = set()
    for idx, ln in enumerate(lines):
        inbound_line_id = ln["inbound_order_line_id"]
        if inbound_line_id in seen:
            raise PurchaseReturnOverQtyError(f"入库行 {inbound_line_id} 在 payload 中重复")
        seen.add(inbound_line_id)
        if inbound_line_id not in contexts:
            raise PurchaseReturnSourceInvalidError(f"入库行不属于源入库单: {inbound_line_id}")
        iol, pol, sol = contexts[inbound_line_id]
        qty = Decimal(str(ln["qty"]))
        remaining = Decimal(str(iol.qty)) - active_return_qty[inbound_line_id]
        if qty > remaining:
            raise PurchaseReturnOverQtyError(
                f"入库行 {inbound_line_id} 可退 {remaining},本次退 {qty}")
        line_total = _money(qty, pol.unit_price)
        total += line_total
        payloads.append({
            "idx": ln.get("sort_order", idx),
            "inbound_line": iol,
            "purchase_line": pol,
            "sales_line": sol,
            "qty": qty,
            "unit_price": Decimal(str(pol.unit_price)),
            "line_total": line_total,
            "remark": ln.get("remark"),
        })
    return payloads, total


async def _create_credit_memo(
    db: AsyncSession, *,
    order: PurchaseReturnOrder,
    payable: Payable,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None,
) -> int | None:
    total = Decimal(str(order.total_amount))
    if total <= 0:
        return None
    memo = APCreditMemo(
        no=await _next_no(db, NumberScope.AP_CREDIT_MEMO),
        payable_id=payable.id,
        purchase_return_order_id=order.id,
        supplier_id=order.supplier_id,
        currency=order.currency,
        memo_type=APCreditMemoType.PURCHASE_RETURN,
        status=APCreditMemoStatus.PENDING_APPROVAL,
        amount=total,
        reason=order.reason,
        created_by=actor_user_id,
    )
    db.add(memo)
    await db.flush()
    await write_audit(
        db, resource_type=AuditResourceType.AP_CREDIT_MEMO,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"payable_id": payable.id, "purchase_return_order_id": order.id,
               "return_kind": order.return_kind},
        commit=False)
    return memo.id


async def _create_customer_refund(
    db: AsyncSession, *,
    order: PurchaseReturnOrder,
    sales_order: SalesOrder,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None,
) -> int | None:
    amount = Decimal(str(order.customer_refund_amount))
    if amount <= 0:
        return None
    refund = CustomerRefund(
        no=await _next_no(db, NumberScope.CUSTOMER_REFUND),
        purchase_return_order_id=order.id,
        sales_order_id=order.sales_order_id,
        customer_id=sales_order.customer_id,
        currency=order.currency,
        status=CustomerRefundStatus.PENDING_PAYMENT,
        amount=amount,
        reason=order.reason,
        created_by=actor_user_id,
    )
    db.add(refund)
    await db.flush()
    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_REFUND,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=refund.id, request=request,
        extra={"purchase_return_order_id": order.id, "sales_order_id": order.sales_order_id,
               "return_kind": order.return_kind, "amount": float(amount)},
        commit=False)
    return refund.id


async def _create_company_loss_entry(
    db: AsyncSession, *,
    order: PurchaseReturnOrder,
    payable: Payable,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None,
) -> int | None:
    amount = Decimal(str(order.company_loss_amount))
    if amount <= 0:
        return None
    now = _utcnow()
    entry = CompanyLossEntry(
        no=await _next_no(db, NumberScope.COMPANY_LOSS),
        purchase_return_order_id=order.id,
        payable_id=payable.id,
        sales_order_id=order.sales_order_id,
        currency=order.currency,
        status=CompanyLossEntryStatus.POSTED,
        amount=amount,
        supplier_payable_amount=order.total_amount,
        customer_refund_amount=order.customer_refund_amount,
        reason=order.reason,
        posted_at=now,
        posted_by=actor_user_id,
        created_by=actor_user_id,
    )
    db.add(entry)
    await db.flush()
    await write_audit(
        db, resource_type=AuditResourceType.COMPANY_LOSS_ENTRY,
        action=AuditAction.POST, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=entry.id, request=request,
        extra={"purchase_return_order_id": order.id, "payable_id": payable.id,
               "return_kind": order.return_kind, "amount": float(amount),
               "supplier_payable_amount": float(Decimal(str(order.total_amount))),
               "customer_refund_amount": float(Decimal(str(order.customer_refund_amount)))},
        commit=False)
    return entry.id


async def _release_paid_amount_for_credit_memo(
    db: AsyncSession, *,
    payable: Payable,
    memo: APCreditMemo,
    locked_payments: dict[int, Payment],
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None,
) -> list[dict]:
    """Move paid-but-now-credited AP back to supplier prepayment by reversing allocations."""
    original = Decimal(str(payable.amount_original))
    credited = Decimal(str(payable.amount_credited))
    allocated = Decimal(str(payable.amount_allocated))
    amount = Decimal(str(memo.amount))
    remaining_debt_after_credit = original - credited - amount
    if remaining_debt_after_credit < 0:
        raise APCreditMemoExceedsOutstandingError(
            "供应商贷项单金额超过应付原始余额")

    release_remaining = allocated - remaining_debt_after_credit
    if release_remaining <= 0:
        return []

    rows = list((await db.execute(
        select(PaymentAllocation)
        .where(
            PaymentAllocation.payable_id == payable.id,
            PaymentAllocation.reversed_at.is_(None),
        )
        .order_by(PaymentAllocation.created_at.desc(), PaymentAllocation.id.desc())
        .with_for_update(of=PaymentAllocation)
    )).scalars().all())
    released: list[dict] = []
    now = _utcnow()
    for alloc in rows:
        if release_remaining <= 0:
            break
        payment = locked_payments.get(alloc.payment_id)
        if payment is None:
            raise APCreditMemoExceedsOutstandingError(
                "供应商贷项单过账期间付款核销发生变化,请重试")
        alloc_amount = Decimal(str(alloc.amount))
        release_amount = min(release_remaining, alloc_amount)
        keep_amount = alloc_amount - release_amount

        alloc.reversed_at = now
        alloc.reversed_by = actor_user_id
        alloc.reverse_reason = f"AP credit memo {memo.no} posted"
        payment.amount_allocated = Decimal(str(payment.amount_allocated)) - alloc_amount
        payable.amount_allocated = Decimal(str(payable.amount_allocated)) - alloc_amount
        await db.flush()

        replacement_id = None
        if keep_amount > 0:
            replacement = PaymentAllocation(
                payment_id=payment.id,
                payable_id=payable.id,
                amount=keep_amount,
                alloc_type=alloc.alloc_type,
                created_by=actor_user_id,
            )
            db.add(replacement)
            payment.amount_allocated = Decimal(str(payment.amount_allocated)) + keep_amount
            payable.amount_allocated = Decimal(str(payable.amount_allocated)) + keep_amount
            await db.flush()
            replacement_id = replacement.id

        release_remaining -= release_amount
        item = {
            "allocation_id": alloc.id,
            "payment_id": payment.id,
            "released_amount": float(release_amount),
            "kept_amount": float(keep_amount),
            "replacement_allocation_id": replacement_id,
        }
        released.append(item)
        await write_audit(
            db, resource_type=AuditResourceType.PAYMENT,
            action=AuditAction.REVERSE, user_id=actor_user_id,
            user_email=actor_user_email, resource_id=payment.id, request=request,
            extra={"payable_id": payable.id, "ap_credit_memo_id": memo.id, **item},
            commit=False)

    if release_remaining > 0:
        raise APCreditMemoExceedsOutstandingError(
            "供应商贷项单已付款部分缺少可反核销记录")
    return released


async def create_purchase_return(
    db: AsyncSession, *,
    inbound_order_id: int,
    reason: str | None,
    lines: list[dict],
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> PurchaseReturnOrder:
    """创建并提交采购退货单。

    仅形成待审核业务单据,不扣库存、不生成供应商贷项单、不冲减应付。
    """
    if not lines:
        raise InboundOrderEmptyError("采购退货单必须至少有一行")

    inbound = (await db.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_order_id)
        .with_for_update())).scalar_one_or_none()
    if inbound is None:
        raise InboundOrderNotFoundError(f"入库单不存在: {inbound_order_id}")
    if inbound.status != InboundOrderStatus.RECEIVED:
        raise PurchaseReturnSourceInvalidError("仅已确认入库单可创建采购退货")

    po = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == inbound.purchase_order_id)
        .with_for_update())).scalar_one()
    sales_order = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == po.source_sales_order_id)
        .with_for_update())).scalar_one()
    await _assert_no_active_outbound(db, sales_order.id)
    await _active_payable_for_update(db, inbound.id)

    line_ids = [ln["inbound_order_line_id"] for ln in lines]
    contexts = await _load_line_context(db, inbound.id, line_ids)
    active_return_qty = await _return_qty_by_inbound_line(
        db, line_ids, statuses=_ACTIVE_RETURN_STATUSES)
    payloads, total = _build_line_payloads(lines, contexts, active_return_qty)

    now = _utcnow()
    order = PurchaseReturnOrder(
        no=await _next_no(db, NumberScope.PURCHASE_RETURN),
        inbound_order_id=inbound.id,
        purchase_order_id=po.id,
        sales_order_id=sales_order.id,
        supplier_id=po.supplier_id,
        currency=po.currency,
        status=PurchaseReturnStatus.PENDING_APPROVAL,
        return_kind=PurchaseReturnKind.PURCHASE_RETURN,
        total_amount=total,
        reason=reason,
        created_by=actor_user_id,
        submitted_at=now,
    )
    db.add(order)
    await db.flush()

    for payload in payloads:
        iol = payload["inbound_line"]
        pol = payload["purchase_line"]
        db.add(PurchaseReturnLine(
            purchase_return_order_id=order.id,
            inbound_order_line_id=iol.id,
            purchase_order_line_id=pol.id,
            sku_id=iol.sku_id,
            name_snapshot=iol.name_snapshot,
            spec_text_snapshot=iol.spec_text_snapshot,
            unit_snapshot=iol.unit_snapshot,
            language=iol.language,
            qty=payload["qty"],
            unit_price=payload["unit_price"],
            line_total=payload["line_total"],
            sort_order=payload["idx"],
            remark=payload["remark"],
        ))

    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request,
        extra={"inbound_order_id": inbound.id, "purchase_order_id": po.id},
        commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def create_in_transit_cancellation(
    db: AsyncSession, *,
    inbound_order_id: int,
    reason: str | None,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> PurchaseReturnOrder:
    """创建并提交未确认入库/在途取消单。

    货未入库,没有销售单维度库存;单据承载供应商接受取消事实,后续确认时关闭在途入库链路,
    并生成供应商贷项单。数量按整张在途入库单全量取消,不做部分改行。
    """
    inbound = (await db.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_order_id)
        .with_for_update())).scalar_one_or_none()
    if inbound is None:
        raise InboundOrderNotFoundError(f"入库单不存在: {inbound_order_id}")
    if inbound.status != InboundOrderStatus.IN_TRANSIT:
        raise PurchaseReturnSourceInvalidError("仅未确认入库/在途入库单可创建在途取消单")

    po = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == inbound.purchase_order_id)
        .with_for_update())).scalar_one()
    sales_order = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == po.source_sales_order_id)
        .with_for_update())).scalar_one()
    await _assert_no_active_outbound(db, sales_order.id)
    await _assert_no_pending_reverse_order(db, inbound.id)
    await _active_payable_for_update(db, inbound.id)

    inbound_lines = list((await db.execute(
        select(InboundOrderLine)
        .where(InboundOrderLine.inbound_order_id == inbound.id)
        .order_by(InboundOrderLine.sort_order, InboundOrderLine.id)
    )).scalars().all())
    if not inbound_lines:
        raise InboundOrderEmptyError("在途取消单必须至少有一行")

    line_ids = [line.id for line in inbound_lines]
    contexts = await _load_line_context(db, inbound.id, line_ids)
    active_return_qty = await _return_qty_by_inbound_line(
        db, line_ids, statuses=_ACTIVE_RETURN_STATUSES)
    payloads, total = _build_line_payloads(
        [{"inbound_order_line_id": line.id, "qty": line.qty, "sort_order": line.sort_order,
          "remark": line.remark} for line in inbound_lines],
        contexts,
        active_return_qty,
    )

    now = _utcnow()
    order = PurchaseReturnOrder(
        no=await _next_no(db, NumberScope.PURCHASE_RETURN),
        inbound_order_id=inbound.id,
        purchase_order_id=po.id,
        sales_order_id=sales_order.id,
        supplier_id=po.supplier_id,
        currency=po.currency,
        status=PurchaseReturnStatus.PENDING_APPROVAL,
        return_kind=PurchaseReturnKind.IN_TRANSIT_CANCELLATION,
        total_amount=total,
        reason=reason,
        created_by=actor_user_id,
        submitted_at=now,
    )
    db.add(order)
    await db.flush()

    for payload in payloads:
        iol = payload["inbound_line"]
        pol = payload["purchase_line"]
        db.add(PurchaseReturnLine(
            purchase_return_order_id=order.id,
            inbound_order_line_id=iol.id,
            purchase_order_line_id=pol.id,
            sku_id=iol.sku_id,
            name_snapshot=iol.name_snapshot,
            spec_text_snapshot=iol.spec_text_snapshot,
            unit_snapshot=iol.unit_snapshot,
            language=iol.language,
            qty=payload["qty"],
            unit_price=payload["unit_price"],
            line_total=payload["line_total"],
            sort_order=payload["idx"],
            remark=payload["remark"],
        ))

    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request,
        extra={"inbound_order_id": inbound.id, "purchase_order_id": po.id,
               "reverse_kind": "IN_TRANSIT_CANCELLATION"},
        commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def create_company_assumed_cancellation(
    db: AsyncSession, *,
    inbound_order_id: int,
    reason: str | None,
    customer_refund_amount,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> PurchaseReturnOrder:
    """创建公司承担型取消单。

    供应商不接受取消/退回,公司仍决定对客户承担。该单据不代表供应商接受,所以后续确认
    不生成供应商贷项单、不冲 payable;金额守恒为 company_loss = 保留供应商应付成本 + 客户退款。
    """
    inbound = (await db.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_order_id)
        .with_for_update())).scalar_one_or_none()
    if inbound is None:
        raise InboundOrderNotFoundError(f"入库单不存在: {inbound_order_id}")
    if inbound.status not in {InboundOrderStatus.IN_TRANSIT, InboundOrderStatus.RECEIVED}:
        raise PurchaseReturnSourceInvalidError("仅在途或已确认入库单可创建公司承担型取消")

    po = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == inbound.purchase_order_id)
        .with_for_update())).scalar_one()
    sales_order = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == po.source_sales_order_id)
        .with_for_update())).scalar_one()
    await _assert_no_active_outbound(db, sales_order.id)
    await _assert_no_pending_reverse_order(db, inbound.id)
    await _active_payable_for_update(db, inbound.id)

    inbound_lines = list((await db.execute(
        select(InboundOrderLine)
        .where(InboundOrderLine.inbound_order_id == inbound.id)
        .order_by(InboundOrderLine.sort_order, InboundOrderLine.id)
    )).scalars().all())
    if not inbound_lines:
        raise InboundOrderEmptyError("公司承担型取消单必须至少有一行")

    line_ids = [line.id for line in inbound_lines]
    contexts = await _load_line_context(db, inbound.id, line_ids)
    active_return_qty = await _return_qty_by_inbound_line(
        db, line_ids, statuses=_ACTIVE_RETURN_STATUSES)
    line_payload = []
    for line in inbound_lines:
        remaining = Decimal(str(line.qty)) - active_return_qty[line.id]
        if remaining > 0:
            line_payload.append({
                "inbound_order_line_id": line.id,
                "qty": remaining,
                "sort_order": line.sort_order,
                "remark": line.remark,
            })
    if not line_payload:
        raise PurchaseReturnOverQtyError("源入库单已无可取消数量")
    payloads, total = _build_line_payloads(line_payload, contexts, active_return_qty)

    refund_amount = Decimal(str(customer_refund_amount or 0)).quantize(
        _CENT, rounding=ROUND_HALF_UP)
    if refund_amount < 0:
        raise PurchaseReturnSourceInvalidError("客户退款金额不可为负")
    company_loss_amount = (total + refund_amount).quantize(_CENT, rounding=ROUND_HALF_UP)

    now = _utcnow()
    order = PurchaseReturnOrder(
        no=await _next_no(db, NumberScope.PURCHASE_RETURN),
        inbound_order_id=inbound.id,
        purchase_order_id=po.id,
        sales_order_id=sales_order.id,
        supplier_id=po.supplier_id,
        currency=po.currency,
        status=PurchaseReturnStatus.PENDING_APPROVAL,
        return_kind=PurchaseReturnKind.COMPANY_ASSUMED_CANCELLATION,
        total_amount=total,
        customer_refund_amount=refund_amount,
        company_loss_amount=company_loss_amount,
        reason=reason,
        created_by=actor_user_id,
        submitted_at=now,
    )
    db.add(order)
    await db.flush()

    for payload in payloads:
        iol = payload["inbound_line"]
        pol = payload["purchase_line"]
        db.add(PurchaseReturnLine(
            purchase_return_order_id=order.id,
            inbound_order_line_id=iol.id,
            purchase_order_line_id=pol.id,
            sku_id=iol.sku_id,
            name_snapshot=iol.name_snapshot,
            spec_text_snapshot=iol.spec_text_snapshot,
            unit_snapshot=iol.unit_snapshot,
            language=iol.language,
            qty=payload["qty"],
            unit_price=payload["unit_price"],
            line_total=payload["line_total"],
            sort_order=payload["idx"],
            remark=payload["remark"],
        ))

    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request,
        extra={"inbound_order_id": inbound.id, "purchase_order_id": po.id,
               "reverse_kind": "COMPANY_ASSUMED_CANCELLATION",
               "customer_refund_amount": float(refund_amount),
               "company_loss_amount": float(company_loss_amount)},
        commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def approve_purchase_return(
    db: AsyncSession, *, order_id: int, actor_user_id: int, actor_user_email: str,
    request: Request | None = None,
) -> PurchaseReturnOrder:
    order = (await db.execute(
        select(PurchaseReturnOrder).where(PurchaseReturnOrder.id == order_id)
        .with_for_update())).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnNotFoundError(f"采购退货单不存在: {order_id}")
    if order.status != PurchaseReturnStatus.PENDING_APPROVAL:
        raise PurchaseReturnSourceInvalidError("仅待审核采购退货单可审核通过")
    order.status = PurchaseReturnStatus.APPROVED
    order.approved_at = _utcnow()
    order.approved_by = actor_user_id
    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.APPROVE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request, extra={}, commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def reject_purchase_return(
    db: AsyncSession, *, order_id: int, reject_reason: str | None, actor_user_id: int,
    actor_user_email: str, request: Request | None = None,
) -> PurchaseReturnOrder:
    order = (await db.execute(
        select(PurchaseReturnOrder).where(PurchaseReturnOrder.id == order_id)
        .with_for_update())).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnNotFoundError(f"采购退货单不存在: {order_id}")
    if order.status != PurchaseReturnStatus.PENDING_APPROVAL:
        raise PurchaseReturnSourceInvalidError("仅待审核采购退货单可驳回")
    order.status = PurchaseReturnStatus.REJECTED
    order.rejected_at = _utcnow()
    order.rejected_by = actor_user_id
    order.reject_reason = reject_reason
    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.REJECT, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request, extra={"reject_reason": reject_reason},
        commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def confirm_return_shipment(
    db: AsyncSession, *, order_id: int, return_shipment_reference: str | None,
    return_note: str | None, actor_user_id: int, actor_user_email: str,
    request: Request | None = None,
) -> PurchaseReturnOrder:
    """确认退货出库。

    这一步扣减销售单维度库存,并生成待财务审核的供应商贷项单。
    """
    order = (await db.execute(
        select(PurchaseReturnOrder).where(PurchaseReturnOrder.id == order_id)
        .with_for_update())).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnNotFoundError(f"采购退货单不存在: {order_id}")
    if order.status != PurchaseReturnStatus.APPROVED:
        raise PurchaseReturnSourceInvalidError("仅已审核采购退货单可确认退货出库")
    _assert_return_kind(
        order, PurchaseReturnKind.PURCHASE_RETURN,
        "在途取消单不可确认退货出库;请使用确认在途取消")

    await _assert_no_active_outbound(db, order.sales_order_id)
    lines = await list_lines(db, order.id)
    impacts = [
        StockImpact(
            sales_order_id=order.sales_order_id,
            sku_id=line.sku_id,
            source_line_id=line.id,
            qty=Decimal(str(line.qty)),
        )
        for line in lines
    ]
    from app.services import stock_ledger_service

    await stock_ledger_service.lock_sales_orders(db, [order.sales_order_id])
    await _assert_stock_available(db, impacts)
    payable = await _active_payable_for_update(db, order.inbound_order_id)

    now = _utcnow()
    await stock_ledger_service.record_purchase_return_issue(
        db,
        purchase_return_order_id=order.id,
        impacts=impacts,
        occurred_at=now,
        actor_user_id=actor_user_id,
        note=return_note or order.reason,
    )

    order.status = PurchaseReturnStatus.RETURNED
    order.returned_at = now
    order.returned_by = actor_user_id
    order.return_shipment_reference = return_shipment_reference
    order.return_note = return_note

    memo_id = await _create_credit_memo(
        db, order=order, payable=payable, actor_user_id=actor_user_id,
        actor_user_email=actor_user_email, request=request)

    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.RETURN_SHIP, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request,
        extra={"ap_credit_memo_id": memo_id},
        commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def confirm_in_transit_cancellation(
    db: AsyncSession, *, order_id: int, cancellation_reference: str | None,
    cancellation_note: str | None, actor_user_id: int, actor_user_email: str,
    request: Request | None = None,
) -> PurchaseReturnOrder:
    """确认在途取消。

    这一步关闭 IN_TRANSIT 入库单并释放 PO 在途额度;不写库存流水,只生成待财务审核的供应商贷项单。
    """
    order = (await db.execute(
        select(PurchaseReturnOrder).where(PurchaseReturnOrder.id == order_id)
        .with_for_update())).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnNotFoundError(f"采购退货单不存在: {order_id}")
    if order.status != PurchaseReturnStatus.APPROVED:
        raise PurchaseReturnSourceInvalidError("仅已审核在途取消单可确认取消")
    _assert_return_kind(
        order, PurchaseReturnKind.IN_TRANSIT_CANCELLATION,
        "采购退货单不可确认在途取消;请使用确认退货出库")

    await _assert_no_active_outbound(db, order.sales_order_id)
    inbound = (await db.execute(
        select(InboundOrder).where(InboundOrder.id == order.inbound_order_id)
        .with_for_update())).scalar_one_or_none()
    if inbound is None:
        raise InboundOrderNotFoundError(f"入库单不存在: {order.inbound_order_id}")
    assert_transition(INBOUND_ORDER_TRANSITIONS, inbound.status, InboundOrderStatus.CANCELLED,
                      InboundOrderInvalidTransitionError)
    payable = await _active_payable_for_update(db, inbound.id)

    now = _utcnow()
    inbound.status = InboundOrderStatus.CANCELLED
    inbound.arrived_at = None
    order.status = PurchaseReturnStatus.RETURNED
    order.returned_at = now
    order.returned_by = actor_user_id
    order.return_shipment_reference = cancellation_reference
    order.return_note = cancellation_note

    memo_id = await _create_credit_memo(
        db, order=order, payable=payable, actor_user_id=actor_user_id,
        actor_user_email=actor_user_email, request=request)

    await write_audit(
        db, resource_type=AuditResourceType.INBOUND_ORDER,
        action=AuditAction.IN_TRANSIT_CANCEL, user_id=actor_user_id,
        user_email=actor_user_email, resource_id=inbound.id, request=request,
        extra={"purchase_return_order_id": order.id, "ap_credit_memo_id": memo_id},
        commit=False)
    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.IN_TRANSIT_CANCEL, user_id=actor_user_id,
        user_email=actor_user_email, resource_id=order.id, request=request,
        extra={"inbound_order_id": inbound.id, "ap_credit_memo_id": memo_id},
        commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def confirm_company_assumed_cancellation(
    db: AsyncSession, *, order_id: int, cancellation_reference: str | None,
    cancellation_note: str | None, actor_user_id: int, actor_user_email: str,
    request: Request | None = None,
) -> PurchaseReturnOrder:
    """确认公司承担型取消。

    - 供应商应付保持原样,不生成供应商贷项单;
    - RECEIVED 入库:库存从 available 转入 disposition,仍挂原销售单;
    - IN_TRANSIT 入库:由本真实逆向单关闭在途入库,不写库存流水;
    - 客户退款单与公司损失确认单在同一事务内生成。
    """
    from app.services import stock_ledger_service

    order = (await db.execute(
        select(PurchaseReturnOrder).where(PurchaseReturnOrder.id == order_id)
        .with_for_update())).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnNotFoundError(f"采购退货单不存在: {order_id}")
    if order.status != PurchaseReturnStatus.APPROVED:
        raise PurchaseReturnSourceInvalidError("仅已审核公司承担型取消单可确认")
    _assert_return_kind(
        order, PurchaseReturnKind.COMPANY_ASSUMED_CANCELLATION,
        "仅公司承担型取消单可确认公司承担取消")

    await _assert_no_active_outbound(db, order.sales_order_id)
    await stock_ledger_service.lock_sales_orders(db, [order.sales_order_id])
    sales_order = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == order.sales_order_id)
        .with_for_update())).scalar_one()
    inbound = (await db.execute(
        select(InboundOrder).where(InboundOrder.id == order.inbound_order_id)
        .with_for_update())).scalar_one_or_none()
    if inbound is None:
        raise InboundOrderNotFoundError(f"入库单不存在: {order.inbound_order_id}")
    if inbound.status not in {InboundOrderStatus.IN_TRANSIT, InboundOrderStatus.RECEIVED}:
        raise PurchaseReturnSourceInvalidError("源入库单状态已不允许确认公司承担型取消")
    payable = await _active_payable_for_update(db, inbound.id)

    lines = await list_lines(db, order.id)
    impacts = [
        StockImpact(
            sales_order_id=order.sales_order_id,
            sku_id=line.sku_id,
            source_line_id=line.id,
            qty=Decimal(str(line.qty)),
        )
        for line in lines
    ]
    now = _utcnow()
    if inbound.status == InboundOrderStatus.RECEIVED:
        await _assert_stock_available(db, impacts)
        await stock_ledger_service.record_company_assumed_disposition_hold(
            db,
            purchase_return_order_id=order.id,
            impacts=impacts,
            occurred_at=now,
            actor_user_id=actor_user_id,
            note=cancellation_note or order.reason,
        )
    else:
        assert_transition(INBOUND_ORDER_TRANSITIONS, inbound.status, InboundOrderStatus.CANCELLED,
                          InboundOrderInvalidTransitionError)
        inbound.status = InboundOrderStatus.CANCELLED
        inbound.arrived_at = None

    order.status = PurchaseReturnStatus.COMPLETED
    order.returned_at = now
    order.returned_by = actor_user_id
    order.return_shipment_reference = cancellation_reference
    order.return_note = cancellation_note

    refund_id = await _create_customer_refund(
        db, order=order, sales_order=sales_order, actor_user_id=actor_user_id,
        actor_user_email=actor_user_email, request=request)
    loss_id = await _create_company_loss_entry(
        db, order=order, payable=payable, actor_user_id=actor_user_id,
        actor_user_email=actor_user_email, request=request)

    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.CANCEL, user_id=actor_user_id,
        user_email=actor_user_email, resource_id=order.id, request=request,
        extra={"inbound_order_id": inbound.id, "customer_refund_id": refund_id,
               "company_loss_entry_id": loss_id,
               "return_kind": order.return_kind},
        commit=False)
    if inbound.status == InboundOrderStatus.CANCELLED:
        await write_audit(
            db, resource_type=AuditResourceType.INBOUND_ORDER,
            action=AuditAction.CANCEL, user_id=actor_user_id,
            user_email=actor_user_email, resource_id=inbound.id, request=request,
            extra={"purchase_return_order_id": order.id,
                   "company_loss_entry_id": loss_id},
            commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def get_order(db: AsyncSession, order_id: int) -> PurchaseReturnOrder:
    order = (await db.execute(
        select(PurchaseReturnOrder).where(PurchaseReturnOrder.id == order_id)
    )).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnNotFoundError(f"采购退货单不存在: {order_id}")
    return order


async def list_lines(db: AsyncSession, order_id: int) -> list[PurchaseReturnLine]:
    return list((await db.execute(
        select(PurchaseReturnLine)
        .where(PurchaseReturnLine.purchase_return_order_id == order_id)
        .order_by(PurchaseReturnLine.sort_order, PurchaseReturnLine.id)
    )).scalars().all())


async def get_ap_credit_memo(db: AsyncSession, order_id: int) -> APCreditMemo | None:
    return (await db.execute(
        select(APCreditMemo)
        .where(
            APCreditMemo.purchase_return_order_id == order_id,
            APCreditMemo.status != APCreditMemoStatus.VOIDED,
        )
        .order_by(APCreditMemo.created_at.desc(), APCreditMemo.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def get_customer_refund(db: AsyncSession, order_id: int) -> CustomerRefund | None:
    return (await db.execute(
        select(CustomerRefund)
        .where(
            CustomerRefund.purchase_return_order_id == order_id,
            CustomerRefund.status != CustomerRefundStatus.VOIDED,
        )
        .order_by(CustomerRefund.created_at.desc(), CustomerRefund.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def get_company_loss_entry(db: AsyncSession, order_id: int) -> CompanyLossEntry | None:
    return (await db.execute(
        select(CompanyLossEntry)
        .where(
            CompanyLossEntry.purchase_return_order_id == order_id,
            CompanyLossEntry.status != CompanyLossEntryStatus.VOIDED,
        )
        .order_by(CompanyLossEntry.created_at.desc(), CompanyLossEntry.id.desc())
        .limit(1)
    )).scalar_one_or_none()


async def returnable_lines(db: AsyncSession, inbound_order_id: int) -> list[dict]:
    inbound = (await db.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_order_id)
    )).scalar_one_or_none()
    if inbound is None:
        raise InboundOrderNotFoundError(f"入库单不存在: {inbound_order_id}")
    if inbound.status != InboundOrderStatus.RECEIVED:
        raise PurchaseReturnSourceInvalidError("仅已确认入库单可创建采购退货")
    lines = list((await db.execute(
        select(InboundOrderLine)
        .where(InboundOrderLine.inbound_order_id == inbound_order_id)
        .order_by(InboundOrderLine.sort_order, InboundOrderLine.id)
    )).scalars().all())
    line_ids = [line.id for line in lines]
    active_qty = await _return_qty_by_inbound_line(
        db, line_ids, statuses=_ACTIVE_RETURN_STATUSES)
    returned_qty = await _return_qty_by_inbound_line(
        db, line_ids, statuses=(PurchaseReturnStatus.RETURNED,))
    return [{
        "inbound_order_line_id": line.id,
        "purchase_order_line_id": line.purchase_order_line_id,
        "sku_id": line.sku_id,
        "name_snapshot": line.name_snapshot,
        "spec_text_snapshot": line.spec_text_snapshot,
        "unit_snapshot": line.unit_snapshot,
        "language": line.language,
        "received_qty": float(line.qty),
        "returned_qty": float(returned_qty[line.id]),
        "in_process_return_qty": float(active_qty[line.id] - returned_qty[line.id]),
        "returnable_qty": float(Decimal(str(line.qty)) - active_qty[line.id]),
        "remark": line.remark,
    } for line in lines]


async def get_detail(db: AsyncSession, order_id: int) -> dict:
    order = await get_order(db, order_id)
    lines = await list_lines(db, order.id)
    memo = await get_ap_credit_memo(db, order.id)
    refund = await get_customer_refund(db, order.id)
    loss = await get_company_loss_entry(db, order.id)
    return {
        "order": order,
        "lines": lines,
        "ap_credit_memo": memo,
        "customer_refund": refund,
        "company_loss_entry": loss,
    }


async def list_orders(db: AsyncSession, *, status: str | None = None,
                      inbound_order_id: int | None = None,
                      purchase_order_id: int | None = None,
                      supplier_id: int | None = None,
                      q: str | None = None,
                      page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    conds = []
    if status:
        conds.append(PurchaseReturnOrder.status == status)
    if inbound_order_id:
        conds.append(PurchaseReturnOrder.inbound_order_id == inbound_order_id)
    if purchase_order_id:
        conds.append(PurchaseReturnOrder.purchase_order_id == purchase_order_id)
    if supplier_id:
        conds.append(PurchaseReturnOrder.supplier_id == supplier_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(
            PurchaseReturnOrder.no.ilike(like)
            | InboundOrder.no.ilike(like)
            | PurchaseOrder.no.ilike(like)
        )

    line_count = (select(func.count(PurchaseReturnLine.id))
                  .where(PurchaseReturnLine.purchase_return_order_id
                         == PurchaseReturnOrder.id).scalar_subquery())
    total_qty = (select(func.coalesce(func.sum(PurchaseReturnLine.qty), 0))
                 .where(PurchaseReturnLine.purchase_return_order_id
                        == PurchaseReturnOrder.id).scalar_subquery())
    memo_status = (select(APCreditMemo.status)
                   .where(
                       APCreditMemo.purchase_return_order_id == PurchaseReturnOrder.id,
                       APCreditMemo.status != APCreditMemoStatus.VOIDED,
                   )
                   .order_by(APCreditMemo.created_at.desc(), APCreditMemo.id.desc())
                   .limit(1)
                   .scalar_subquery())
    base = (select(PurchaseReturnOrder, InboundOrder.no, PurchaseOrder.no,
                   line_count.label("line_count"), total_qty.label("total_qty"),
                   memo_status.label("ap_credit_memo_status"))
            .join(InboundOrder, InboundOrder.id == PurchaseReturnOrder.inbound_order_id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseReturnOrder.purchase_order_id)
            .where(*conds))
    rows, total = await paginate(
        db, base.order_by(PurchaseReturnOrder.created_at.desc()),
        page=page, size=size, scalars=False)
    return [{
        "id": o.id, "no": o.no, "status": o.status, "return_kind": o.return_kind,
        "inbound_order_id": o.inbound_order_id, "inbound_order_no": in_no,
        "purchase_order_id": o.purchase_order_id, "purchase_order_no": po_no,
        "sales_order_id": o.sales_order_id, "supplier_id": o.supplier_id,
        "currency": o.currency, "total_amount": float(o.total_amount),
        "customer_refund_amount": float(o.customer_refund_amount),
        "company_loss_amount": float(o.company_loss_amount),
        "line_count": line_count, "total_qty": float(total_qty),
        "ap_credit_memo_status": ap_credit_memo_status,
        "submitted_at": o.submitted_at, "created_at": o.created_at,
    } for o, in_no, po_no, line_count, total_qty, ap_credit_memo_status in rows], total


async def get_credit_memo(db: AsyncSession, memo_id: int) -> APCreditMemo:
    memo = (await db.execute(
        select(APCreditMemo).where(APCreditMemo.id == memo_id)
    )).scalar_one_or_none()
    if memo is None:
        raise NotFoundError(f"供应商贷项单不存在: {memo_id}")
    return memo


async def list_credit_memos(db: AsyncSession, *, status: str | None = None,
                            supplier_id: int | None = None,
                            payable_id: int | None = None,
                            purchase_return_order_id: int | None = None,
                            page: int = 1, size: int = 20) -> tuple[list[APCreditMemo], int]:
    conds = [APCreditMemo.status != APCreditMemoStatus.VOIDED]
    if status:
        conds.append(APCreditMemo.status == status)
    if supplier_id:
        conds.append(APCreditMemo.supplier_id == supplier_id)
    if payable_id:
        conds.append(APCreditMemo.payable_id == payable_id)
    if purchase_return_order_id:
        conds.append(APCreditMemo.purchase_return_order_id == purchase_return_order_id)
    base = select(APCreditMemo).where(*conds).order_by(APCreditMemo.created_at.desc())
    return await paginate(db, base, page=page, size=size)


async def post_credit_memo(
    db: AsyncSession, *, memo_id: int, actor_user_id: int, actor_user_email: str,
    request: Request | None = None,
) -> APCreditMemo:
    memo = (await db.execute(
        select(APCreditMemo).where(APCreditMemo.id == memo_id)
        .with_for_update())).scalar_one_or_none()
    if memo is None:
        raise NotFoundError(f"供应商贷项单不存在: {memo_id}")
    if memo.status != APCreditMemoStatus.PENDING_APPROVAL:
        raise PurchaseReturnSourceInvalidError("仅待财务审核供应商贷项单可过账")

    payment_ids = await _active_payment_ids_for_payable(db, memo.payable_id)
    locked_payments = await _lock_payments_for_update(db, payment_ids)
    payable = await _active_payable_by_id_for_update(db, memo.payable_id)
    order = (await db.execute(
        select(PurchaseReturnOrder).where(
            PurchaseReturnOrder.id == memo.purchase_return_order_id,
        ).with_for_update())).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnSourceInvalidError("供应商贷项单关联的采购退货单不存在")

    amount = Decimal(str(memo.amount))
    released_allocations = await _release_paid_amount_for_credit_memo(
        db, payable=payable, memo=memo, locked_payments=locked_payments,
        actor_user_id=actor_user_id,
        actor_user_email=actor_user_email, request=request)
    outstanding_before_credit = (
        Decimal(str(payable.amount_original))
        - Decimal(str(payable.amount_credited))
        - Decimal(str(payable.amount_allocated))
    )
    if amount > outstanding_before_credit:
        raise APCreditMemoExceedsOutstandingError(
            "供应商贷项单金额超过可冲减的应付金额")

    memo.status = APCreditMemoStatus.POSTED
    memo.posted_at = _utcnow()
    memo.posted_by = actor_user_id
    payable.amount_credited = Decimal(str(payable.amount_credited)) + amount
    await write_audit(
        db, resource_type=AuditResourceType.AP_CREDIT_MEMO,
        action=AuditAction.POST, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"payable_id": payable.id, "purchase_return_order_id": order.id,
               "return_kind": order.return_kind, "amount": float(amount),
               "released_payment_allocations": released_allocations},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo


async def _open_credit_memo_id_for_order(db: AsyncSession, order_id: int) -> int | None:
    return (await db.execute(
        select(APCreditMemo.id)
        .where(
            APCreditMemo.purchase_return_order_id == order_id,
            APCreditMemo.status.in_(_OPEN_CREDIT_MEMO_STATUSES),
        )
        .limit(1)
    )).scalar_one_or_none()


async def reject_credit_memo(
    db: AsyncSession, *, memo_id: int, reject_reason: str | None, actor_user_id: int,
    actor_user_email: str, request: Request | None = None,
) -> APCreditMemo:
    memo = (await db.execute(
        select(APCreditMemo).where(APCreditMemo.id == memo_id)
        .with_for_update())).scalar_one_or_none()
    if memo is None:
        raise NotFoundError(f"供应商贷项单不存在: {memo_id}")
    if memo.status != APCreditMemoStatus.PENDING_APPROVAL:
        raise PurchaseReturnSourceInvalidError("仅待财务审核供应商贷项单可驳回")
    memo.status = APCreditMemoStatus.REJECTED
    memo.rejected_at = _utcnow()
    memo.rejected_by = actor_user_id
    memo.reject_reason = reject_reason
    await write_audit(
        db, resource_type=AuditResourceType.AP_CREDIT_MEMO,
        action=AuditAction.REJECT, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"reject_reason": reject_reason},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo


async def resubmit_credit_memo(
    db: AsyncSession, *, memo_id: int, actor_user_id: int, actor_user_email: str,
    request: Request | None = None,
) -> APCreditMemo:
    """重新提交被驳回的供应商贷项单。

    采购退货/在途取消的实物流转已确认后,财务驳回只否决当前贷项单据,不回滚业务事实。
    重新提交创建一张新的 PENDING_APPROVAL 贷项单,旧 REJECTED 单保留审计。
    """
    old = (await db.execute(
        select(APCreditMemo).where(APCreditMemo.id == memo_id)
        .with_for_update())).scalar_one_or_none()
    if old is None:
        raise NotFoundError(f"供应商贷项单不存在: {memo_id}")
    if old.status != APCreditMemoStatus.REJECTED:
        raise PurchaseReturnSourceInvalidError("仅已驳回供应商贷项单可重新提交")

    if await _open_credit_memo_id_for_order(db, old.purchase_return_order_id) is not None:
        raise PurchaseReturnSourceInvalidError("源采购退货单已有待处理或已过账供应商贷项单")

    order = (await db.execute(
        select(PurchaseReturnOrder).where(
            PurchaseReturnOrder.id == old.purchase_return_order_id,
        ).with_for_update())).scalar_one_or_none()
    if order is None:
        raise PurchaseReturnSourceInvalidError("供应商贷项单关联的采购退货单不存在")
    if order.status != PurchaseReturnStatus.RETURNED:
        raise PurchaseReturnSourceInvalidError("仅已完成退货/取消的源单可重新提交供应商贷项单")

    if await _open_credit_memo_id_for_order(db, old.purchase_return_order_id) is not None:
        raise PurchaseReturnSourceInvalidError("源采购退货单已有待处理或已过账供应商贷项单")

    payable = await _active_payable_by_id_for_update(db, old.payable_id)
    if payable.supplier_id != old.supplier_id or payable.currency != old.currency:
        raise PurchaseReturnSourceInvalidError("供应商贷项单与应付账款供应商或币种不一致")

    memo = APCreditMemo(
        no=await _next_no(db, NumberScope.AP_CREDIT_MEMO),
        payable_id=old.payable_id,
        purchase_return_order_id=old.purchase_return_order_id,
        supplier_id=old.supplier_id,
        currency=old.currency,
        memo_type=old.memo_type,
        status=APCreditMemoStatus.PENDING_APPROVAL,
        amount=old.amount,
        reason=old.reason,
        created_by=actor_user_id,
    )
    db.add(memo)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_ap_credit_memos_preturn_active" in str(exc.orig):
            raise PurchaseReturnSourceInvalidError(
                "源采购退货单已有待处理或已过账供应商贷项单") from exc
        raise

    await write_audit(
        db, resource_type=AuditResourceType.AP_CREDIT_MEMO,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={
            "payable_id": payable.id,
            "purchase_return_order_id": order.id,
            "return_kind": order.return_kind,
            "resubmitted_from_ap_credit_memo_id": old.id,
            "rejected_reason": old.reject_reason,
        },
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo
