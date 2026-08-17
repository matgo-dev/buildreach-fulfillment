from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    APCreditMemoExceedsOutstandingError,
    InboundOrderEmptyError,
    InboundOrderNotFoundError,
    NotFoundError,
    PurchaseReturnNotFoundError,
    PurchaseReturnOverQtyError,
    PurchaseReturnSourceInvalidError,
    PurchaseReturnWouldGoNegativeError,
)
from app.db.models.ap_credit_memo import APCreditMemo, APCreditMemoStatus, APCreditMemoType
from app.db.models.inbound_order import InboundOrder, InboundOrderLine, InboundOrderStatus
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.payable import Payable
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.db.models.purchase_return import (
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

    memo_id = None
    total = Decimal(str(order.total_amount))
    if total > 0:
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
        memo_id = memo.id
        await write_audit(
            db, resource_type=AuditResourceType.AP_CREDIT_MEMO,
            action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
            resource_id=memo.id, request=request,
            extra={"payable_id": payable.id, "purchase_return_order_id": order.id},
            commit=False)

    await write_audit(
        db, resource_type=AuditResourceType.PURCHASE_RETURN_ORDER,
        action=AuditAction.RETURN_SHIP, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request,
        extra={"ap_credit_memo_id": memo_id},
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
    return {"order": order, "lines": lines, "ap_credit_memo": memo}


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
        "id": o.id, "no": o.no, "status": o.status,
        "inbound_order_id": o.inbound_order_id, "inbound_order_no": in_no,
        "purchase_order_id": o.purchase_order_id, "purchase_order_no": po_no,
        "sales_order_id": o.sales_order_id, "supplier_id": o.supplier_id,
        "currency": o.currency, "total_amount": float(o.total_amount),
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

    payable = (await db.execute(
        select(Payable).where(
            Payable.id == memo.payable_id,
            Payable.voided_at.is_(None),
        ).with_for_update())).scalar_one_or_none()
    if payable is None:
        raise PurchaseReturnSourceInvalidError("供应商贷项单关联的应付账款不存在或已作废")
    amount = Decimal(str(memo.amount))
    if amount > Decimal(str(payable.amount_outstanding)):
        raise APCreditMemoExceedsOutstandingError(
            "供应商贷项单金额超过当前未结应付;已付款部分需走供应商退款/预付退回")

    memo.status = APCreditMemoStatus.POSTED
    memo.posted_at = _utcnow()
    memo.posted_by = actor_user_id
    payable.amount_credited = Decimal(str(payable.amount_credited)) + amount
    await write_audit(
        db, resource_type=AuditResourceType.AP_CREDIT_MEMO,
        action=AuditAction.POST, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=memo.id, request=request,
        extra={"payable_id": payable.id, "amount": float(amount)},
        commit=False)
    await db.commit()
    await db.refresh(memo)
    return memo


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
