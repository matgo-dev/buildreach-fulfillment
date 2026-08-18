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
from app.core.exceptions import (
    InboundOrderEmptyError,
    InboundOrderNotFoundError,
    PurchaseReturnOverQtyError,
    PurchaseReturnSourceInvalidError,
    PurchaseReturnWouldGoNegativeError,
)
from app.db.models.inbound_order import InboundOrder, InboundOrderLine, InboundOrderStatus
from app.db.models.inventory_disposition import (
    InventoryDispositionLine,
    InventoryDispositionOrder,
    InventoryDispositionReceiptHandling,
    InventoryDispositionStatus,
)
from app.db.models.outbound_order import OutboundOrder, OutboundOrderStatus
from app.db.models.payable import Payable
from app.db.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.db.models.purchase_return import PurchaseReturnLine, PurchaseReturnOrder, PurchaseReturnStatus
from app.db.models.sales_order import SalesOrderLine
from app.db.models.stock import InventoryBalance
from app.services.numbering import allocate
from app.services.stock_ledger_service import StockImpact

_CENT = Decimal("0.01")


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
        raise PurchaseReturnSourceInvalidError("源入库单没有活动应付,不可创建库存处置单")
    return payable


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
            "销售单已形成出库单,不可走出库前库存处置;请走售后流程")


async def _assert_no_pending_purchase_reverse(db: AsyncSession, inbound_order_id: int) -> None:
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
        raise PurchaseReturnSourceInvalidError("入库单已有待处理采购逆向单据,请先完成或驳回")


async def _active_disposition_id(db: AsyncSession, inbound_order_id: int) -> int | None:
    return (await db.execute(
        select(InventoryDispositionOrder.id)
        .where(
            InventoryDispositionOrder.inbound_order_id == inbound_order_id,
            InventoryDispositionOrder.status != InventoryDispositionStatus.VOIDED,
        )
        .limit(1))).scalar_one_or_none()


async def assert_no_active_disposition(db: AsyncSession, inbound_order_id: int) -> None:
    if await _active_disposition_id(db, inbound_order_id) is not None:
        raise PurchaseReturnSourceInvalidError("入库单已有库存处置单,不可重复创建逆向单据")


async def _returned_qty_by_inbound_line(
    db: AsyncSession,
    inbound_line_ids: list[int],
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
            PurchaseReturnOrder.status.in_({
                PurchaseReturnStatus.PENDING_APPROVAL,
                PurchaseReturnStatus.APPROVED,
                PurchaseReturnStatus.RETURNED,
            }),
        )
        .group_by(PurchaseReturnLine.inbound_order_line_id))).all()
    for line_id, qty in rows:
        result[line_id] = Decimal(str(qty))
    return result


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
                "disposition_qty": float(qty),
            })
    if negatives:
        raise PurchaseReturnWouldGoNegativeError(data={"items": negatives})


def _line_impacts(order: InventoryDispositionOrder,
                  lines: list[InventoryDispositionLine]) -> list[StockImpact]:
    return [
        StockImpact(
            sales_order_id=order.sales_order_id,
            sku_id=line.sku_id,
            source_line_id=line.id,
            qty=Decimal(str(line.qty)),
        )
        for line in lines
    ]


async def _finish_hold(
    db: AsyncSession, *,
    order: InventoryDispositionOrder,
    actor_user_id: int,
    note: str | None,
) -> None:
    from app.services import stock_ledger_service

    lines = await list_lines(db, order.id)
    impacts = _line_impacts(order, lines)
    await _assert_stock_available(db, impacts)
    await stock_ledger_service.record_disposition_hold(
        db,
        inventory_disposition_order_id=order.id,
        impacts=impacts,
        occurred_at=_utcnow(),
        actor_user_id=actor_user_id,
        note=note or order.reason,
    )
    order.status = InventoryDispositionStatus.HELD
    order.held_at = _utcnow()
    order.held_by = actor_user_id


async def create_disposition(
    db: AsyncSession, *,
    inbound_order_id: int,
    receipt_handling: str,
    reason: str | None,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> InventoryDispositionOrder:
    """创建库存处置单。

    已入库货物立即转入待处置;仍在途货物按持久化收货处理口径关闭未收货或继续到仓后
    直接进入待处置库存。本入口只承载履约/库存事实,不生成客户退款或公司损失财务单据。
    """
    if receipt_handling not in InventoryDispositionReceiptHandling.ALL:
        raise PurchaseReturnSourceInvalidError("库存处置收货处理口径无效")

    source = (await db.execute(
        select(
            InboundOrder.purchase_order_id,
            PurchaseOrder.source_sales_order_id,
        )
        .join(PurchaseOrder, PurchaseOrder.id == InboundOrder.purchase_order_id)
        .where(InboundOrder.id == inbound_order_id)
    )).first()
    if source is None:
        raise InboundOrderNotFoundError(f"入库单不存在: {inbound_order_id}")
    source_purchase_order_id, source_sales_order_id = source

    from app.services import stock_ledger_service
    await stock_ledger_service.lock_sales_orders(db, [source_sales_order_id])

    inbound = (await db.execute(
        select(InboundOrder).where(InboundOrder.id == inbound_order_id)
        .with_for_update())).scalar_one_or_none()
    if inbound is None:
        raise InboundOrderNotFoundError(f"入库单不存在: {inbound_order_id}")
    if inbound.purchase_order_id != source_purchase_order_id:
        raise PurchaseReturnSourceInvalidError("入库单来源采购单已变化,请刷新后重试")
    if inbound.status not in {InboundOrderStatus.IN_TRANSIT, InboundOrderStatus.RECEIVED}:
        raise PurchaseReturnSourceInvalidError("仅在途或已确认入库单可创建库存处置单")
    if (inbound.status == InboundOrderStatus.RECEIVED
            and receipt_handling
            != InventoryDispositionReceiptHandling.RECEIVE_TO_DISPOSITION):
        raise PurchaseReturnSourceInvalidError("已入库货物只能转入待处置库存")

    po = (await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == inbound.purchase_order_id)
        .with_for_update())).scalar_one()
    if po.source_sales_order_id != source_sales_order_id:
        raise PurchaseReturnSourceInvalidError("采购单来源销售单已变化,请刷新后重试")
    await _assert_no_active_outbound(db, source_sales_order_id)
    await _assert_no_pending_purchase_reverse(db, inbound.id)
    await assert_no_active_disposition(db, inbound.id)
    payable = await _active_payable_for_update(db, inbound.id)

    inbound_lines = list((await db.execute(
        select(InboundOrderLine)
        .where(InboundOrderLine.inbound_order_id == inbound.id)
        .order_by(InboundOrderLine.sort_order, InboundOrderLine.id)
    )).scalars().all())
    if not inbound_lines:
        raise InboundOrderEmptyError("库存处置单必须至少有一行")

    line_ids = [line.id for line in inbound_lines]
    contexts = await _load_line_context(db, inbound.id, line_ids)
    returned_qty = await _returned_qty_by_inbound_line(db, line_ids)
    payloads = []
    total = Decimal("0")
    for idx, line in enumerate(inbound_lines):
        if line.id not in contexts:
            raise PurchaseReturnSourceInvalidError(f"入库行不属于源入库单: {line.id}")
        iol, pol, _sol = contexts[line.id]
        qty = Decimal(str(iol.qty)) - returned_qty[iol.id]
        if qty <= 0:
            continue
        unit_cost = Decimal(str(pol.unit_price))
        line_cost = _money(qty, unit_cost)
        total += line_cost
        payloads.append((idx, iol, pol, qty, unit_cost, line_cost))
    if not payloads:
        raise PurchaseReturnOverQtyError("源入库单已无可处置数量")

    now = _utcnow()
    order = InventoryDispositionOrder(
        no=await _next_no(db, NumberScope.INVENTORY_DISPOSITION),
        inbound_order_id=inbound.id,
        purchase_order_id=po.id,
        sales_order_id=source_sales_order_id,
        payable_id=payable.id,
        purchase_currency=po.currency,
        status=(
            InventoryDispositionStatus.HELD
            if inbound.status == InboundOrderStatus.RECEIVED
            else (
                InventoryDispositionStatus.CLOSED_WITHOUT_RECEIPT
                if receipt_handling
                == InventoryDispositionReceiptHandling.CLOSE_WITHOUT_RECEIPT
                else InventoryDispositionStatus.PENDING_RECEIPT
            )
        ),
        receipt_handling=receipt_handling,
        supplier_payable_amount=total,
        reason=reason,
        created_by=actor_user_id,
        held_at=now if inbound.status == InboundOrderStatus.RECEIVED else None,
        held_by=actor_user_id if inbound.status == InboundOrderStatus.RECEIVED else None,
    )
    db.add(order)
    await db.flush()
    for idx, iol, pol, qty, unit_cost, line_cost in payloads:
        db.add(InventoryDispositionLine(
            inventory_disposition_order_id=order.id,
            inbound_order_line_id=iol.id,
            purchase_order_line_id=pol.id,
            sku_id=iol.sku_id,
            name_snapshot=iol.name_snapshot,
            spec_text_snapshot=iol.spec_text_snapshot,
            unit_snapshot=iol.unit_snapshot,
            language=iol.language,
            qty=qty,
            unit_cost=unit_cost,
            line_cost=line_cost,
            sort_order=idx,
            remark=iol.remark,
        ))
    await db.flush()

    if inbound.status == InboundOrderStatus.RECEIVED:
        await _finish_hold(db, order=order, actor_user_id=actor_user_id, note=reason)
    elif receipt_handling == InventoryDispositionReceiptHandling.CLOSE_WITHOUT_RECEIPT:
        inbound.status = InboundOrderStatus.CLOSED
        inbound.arrived_at = None
        await write_audit(
            db, resource_type=AuditResourceType.INBOUND_ORDER,
            action=AuditAction.UPDATE, user_id=actor_user_id, user_email=actor_user_email,
            resource_id=inbound.id, request=request,
            extra={"inventory_disposition_order_id": order.id,
                   "receipt_handling": receipt_handling,
                   "payable_id": payable.id},
            commit=False)

    await write_audit(
        db, resource_type=AuditResourceType.INVENTORY_DISPOSITION_ORDER,
        action=AuditAction.CREATE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request,
        extra={"inbound_order_id": inbound.id, "receipt_handling": receipt_handling},
        commit=False)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if "uq_inv_dispositions_inbound_active" in str(exc.orig):
            raise PurchaseReturnSourceInvalidError("入库单已有库存处置单") from exc
        raise
    await db.refresh(order)
    return order


async def receive_pending_disposition(
    db: AsyncSession, *,
    inbound_order_id: int,
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> InventoryDispositionOrder | None:
    """在途入库确认时,把已有待收货库存处置单转为待处置库存。"""
    order = (await db.execute(
        select(InventoryDispositionOrder)
        .where(
            InventoryDispositionOrder.inbound_order_id == inbound_order_id,
            InventoryDispositionOrder.status == InventoryDispositionStatus.PENDING_RECEIPT,
        )
        .with_for_update()
    )).scalar_one_or_none()
    if order is None:
        return None
    from app.services import stock_ledger_service

    await stock_ledger_service.record_inbound_receive(
        db, inbound_order_id=inbound_order_id, occurred_at=None,
        actor_user_id=actor_user_id)
    await _finish_hold(db, order=order, actor_user_id=actor_user_id, note=order.reason)
    await write_audit(
        db, resource_type=AuditResourceType.INVENTORY_DISPOSITION_ORDER,
        action=AuditAction.RECEIVE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request,
        extra={"inbound_order_id": inbound_order_id},
        commit=False)
    return order


async def get_order(db: AsyncSession, order_id: int) -> InventoryDispositionOrder | None:
    return (await db.execute(
        select(InventoryDispositionOrder)
        .where(InventoryDispositionOrder.id == order_id)
    )).scalar_one_or_none()


async def list_lines(db: AsyncSession, order_id: int) -> list[InventoryDispositionLine]:
    return list((await db.execute(
        select(InventoryDispositionLine)
        .where(InventoryDispositionLine.inventory_disposition_order_id == order_id)
        .order_by(InventoryDispositionLine.sort_order, InventoryDispositionLine.id)
    )).scalars().all())


async def get_by_inbound(db: AsyncSession, inbound_order_id: int) -> InventoryDispositionOrder | None:
    return (await db.execute(
        select(InventoryDispositionOrder)
        .where(
            InventoryDispositionOrder.inbound_order_id == inbound_order_id,
            InventoryDispositionOrder.status != InventoryDispositionStatus.VOIDED,
        )
        .order_by(InventoryDispositionOrder.created_at.desc(), InventoryDispositionOrder.id.desc())
        .limit(1)
    )).scalar_one_or_none()
