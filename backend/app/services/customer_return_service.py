from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.codegen import NumberScope, format_code
from app.core.exceptions import (
    CustomerReturnDuplicateLineError,
    CustomerReturnEmptyError,
    CustomerReturnLineNotInOutboundError,
    CustomerReturnOverQtyError,
    CustomerReturnSourceInvalidError,
    NotFoundError,
)
from app.db.models.customer_return import (
    CustomerReturnLine,
    CustomerReturnOrder,
    CustomerReturnStatus,
)
from app.db.models.inbound_order import InboundOrder, InboundOrderStatus
from app.db.models.outbound_order import OutboundOrder, OutboundOrderLine, OutboundOrderStatus
from app.db.models.purchase_order import PurchaseOrderLine
from app.db.models.sales_order import SalesOrder, SalesOrderLine
from app.db.models.shipment_order import ShipmentOrder, ShipmentOrderStatus
from app.services.numbering import allocate
from app.services.stock_ledger_service import StockImpact


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _next_no(db: AsyncSession) -> str:
    period = datetime.now(timezone.utc).strftime("%Y%m")
    seq = await allocate(db, NumberScope.CUSTOMER_RETURN, period)
    return format_code(NumberScope.CUSTOMER_RETURN, seq, period)


async def _returned_qty_by_outbound_line(
    db: AsyncSession,
    outbound_line_ids: list[int],
) -> dict[int, Decimal]:
    result = {line_id: Decimal("0") for line_id in outbound_line_ids}
    if not outbound_line_ids:
        return result
    rows = (await db.execute(
        select(
            CustomerReturnLine.outbound_order_line_id,
            func.coalesce(func.sum(CustomerReturnLine.qty), 0),
        )
        .join(CustomerReturnOrder,
              CustomerReturnOrder.id == CustomerReturnLine.customer_return_order_id)
        .where(
            CustomerReturnLine.outbound_order_line_id.in_(outbound_line_ids),
            CustomerReturnOrder.status != CustomerReturnStatus.VOIDED,
        )
        .group_by(CustomerReturnLine.outbound_order_line_id))).all()
    for line_id, qty in rows:
        result[line_id] = Decimal(str(qty))
    return result


async def _load_line_context(
    db: AsyncSession,
    outbound_order_id: int,
    line_ids: list[int],
) -> dict[int, tuple[OutboundOrderLine, SalesOrderLine]]:
    rows = (await db.execute(
        select(OutboundOrderLine, SalesOrderLine)
        .join(SalesOrderLine, SalesOrderLine.id == OutboundOrderLine.sales_order_line_id)
        .where(
            OutboundOrderLine.outbound_order_id == outbound_order_id,
            OutboundOrderLine.id.in_(line_ids),
        ))).all()
    return {obl.id: (obl, sol) for obl, sol in rows}


def _validate_payload(lines: list[dict]) -> None:
    if not lines:
        raise CustomerReturnEmptyError()
    seen: set[int] = set()
    for line in lines:
        line_id = line["outbound_order_line_id"]
        if line_id in seen:
            raise CustomerReturnDuplicateLineError("客户退货行重复引用同一出库行")
        seen.add(line_id)


def _line_impacts(order: CustomerReturnOrder,
                  lines: list[CustomerReturnLine]) -> list[StockImpact]:
    return [
        StockImpact(
            sales_order_id=order.sales_order_id,
            sku_id=line.sku_id,
            source_line_id=line.id,
            qty=Decimal(str(line.qty)),
        )
        for line in lines
    ]


async def create_return(
    db: AsyncSession, *,
    outbound_order_id: int,
    reason: str | None,
    lines: list[dict],
    actor_user_id: int,
    actor_user_email: str,
    request: Request | None = None,
) -> CustomerReturnOrder:
    _validate_payload(lines)

    source = (await db.execute(
        select(OutboundOrder.sales_order_id)
        .where(OutboundOrder.id == outbound_order_id)
    )).scalar_one_or_none()
    if source is None:
        raise NotFoundError(f"出库单不存在: {outbound_order_id}")

    from app.services import stock_ledger_service
    await stock_ledger_service.lock_sales_orders(db, [source])

    outbound = (await db.execute(
        select(OutboundOrder)
        .where(OutboundOrder.id == outbound_order_id)
        .with_for_update()
    )).scalar_one_or_none()
    if outbound is None:
        raise NotFoundError(f"出库单不存在: {outbound_order_id}")
    if outbound.sales_order_id != source:
        raise CustomerReturnSourceInvalidError("出库单来源销售单已变化,请刷新后重试")
    if outbound.status != OutboundOrderStatus.ISSUED:
        raise CustomerReturnSourceInvalidError("仅已确认出库单可创建客户退货单")
    shipment_status = (await db.execute(
        select(ShipmentOrder.status).where(ShipmentOrder.id == outbound.shipment_id)
    )).scalar_one_or_none()
    if shipment_status not in {ShipmentOrderStatus.LOADED, ShipmentOrderStatus.DEPARTED}:
        raise CustomerReturnSourceInvalidError(
            "柜未封或已取消时不可创建客户退货单;请先完成物流拦截/出库纠错")

    sales_order = (await db.execute(
        select(SalesOrder).where(SalesOrder.id == outbound.sales_order_id).with_for_update()
    )).scalar_one_or_none()
    if sales_order is None:
        raise CustomerReturnSourceInvalidError("出库单关联的销售单不存在")

    line_ids = [line["outbound_order_line_id"] for line in lines]
    contexts = await _load_line_context(db, outbound.id, line_ids)
    returned_qty = await _returned_qty_by_outbound_line(db, line_ids)
    payloads = []
    for idx, line in enumerate(lines):
        line_id = line["outbound_order_line_id"]
        if line_id not in contexts:
            raise CustomerReturnLineNotInOutboundError(f"出库行不属于源出库单: {line_id}")
        outbound_line, sales_line = contexts[line_id]
        qty = Decimal(str(line["qty"]))
        remaining = Decimal(str(outbound_line.qty)) - returned_qty[line_id]
        if qty > remaining:
            raise CustomerReturnOverQtyError(data={
                "outbound_order_line_id": line_id,
                "outbound_qty": float(outbound_line.qty),
                "returned_qty": float(returned_qty[line_id]),
                "requested_qty": float(qty),
                "remaining_qty": float(remaining),
            })
        payloads.append((idx, line, outbound_line, sales_line, qty))

    now = _utcnow()
    order = CustomerReturnOrder(
        no=await _next_no(db),
        outbound_order_id=outbound.id,
        sales_order_id=outbound.sales_order_id,
        customer_id=sales_order.customer_id,
        status=CustomerReturnStatus.RECEIVED,
        reason=reason,
        received_at=now,
        received_by=actor_user_id,
        created_by=actor_user_id,
    )
    db.add(order)
    await db.flush()

    created_lines: list[CustomerReturnLine] = []
    for idx, line, outbound_line, sales_line, qty in payloads:
        row = CustomerReturnLine(
            customer_return_order_id=order.id,
            outbound_order_line_id=outbound_line.id,
            sales_order_line_id=sales_line.id,
            sku_id=outbound_line.sku_id,
            name_snapshot=sales_line.name_snapshot,
            spec_text_snapshot=sales_line.spec_text_snapshot,
            unit_snapshot=sales_line.unit_snapshot,
            language=sales_line.language,
            qty=qty,
            sort_order=line.get("sort_order", idx),
            remark=line.get("remark"),
        )
        db.add(row)
        created_lines.append(row)
    await db.flush()

    await stock_ledger_service.record_customer_return_receive(
        db,
        customer_return_order_id=order.id,
        impacts=_line_impacts(order, created_lines),
        occurred_at=now,
        actor_user_id=actor_user_id,
        note=reason,
    )
    await write_audit(
        db, resource_type=AuditResourceType.CUSTOMER_RETURN_ORDER,
        action=AuditAction.RECEIVE, user_id=actor_user_id, user_email=actor_user_email,
        resource_id=order.id, request=request,
        extra={"outbound_order_id": outbound.id, "sales_order_id": outbound.sales_order_id},
        commit=False)
    await db.commit()
    await db.refresh(order)
    return order


async def get_order(db: AsyncSession, order_id: int) -> CustomerReturnOrder:
    order = (await db.execute(
        select(CustomerReturnOrder).where(CustomerReturnOrder.id == order_id)
    )).scalar_one_or_none()
    if order is None:
        raise NotFoundError(f"客户退货单不存在: {order_id}")
    return order


async def list_lines(db: AsyncSession, order_id: int) -> list[CustomerReturnLine]:
    return list((await db.execute(
        select(CustomerReturnLine)
        .where(CustomerReturnLine.customer_return_order_id == order_id)
        .order_by(CustomerReturnLine.sort_order, CustomerReturnLine.id)
    )).scalars().all())


async def trace_source_ids(db: AsyncSession, order_id: int) -> dict:
    rows = (await db.execute(
        select(PurchaseOrderLine.purchase_order_id, InboundOrder.id)
        .select_from(CustomerReturnLine)
        .join(PurchaseOrderLine,
              PurchaseOrderLine.source_sales_order_line_id == CustomerReturnLine.sales_order_line_id)
        .join(InboundOrder, InboundOrder.purchase_order_id == PurchaseOrderLine.purchase_order_id)
        .where(
            CustomerReturnLine.customer_return_order_id == order_id,
            InboundOrder.status == InboundOrderStatus.RECEIVED,
        )
    )).all()
    purchase_order_ids: dict[int, None] = {}
    inbound_order_ids: dict[int, None] = {}
    for po_id, inbound_id in rows:
        purchase_order_ids[po_id] = None
        inbound_order_ids[inbound_id] = None
    return {
        "purchase_order_ids": list(purchase_order_ids),
        "inbound_order_ids": list(inbound_order_ids),
    }


async def get_detail(db: AsyncSession, order_id: int) -> dict:
    order = await get_order(db, order_id)
    return {
        "order": order,
        "lines": await list_lines(db, order.id),
        "trace": await trace_source_ids(db, order.id),
    }


async def returnable_lines(db: AsyncSession, outbound_order_id: int) -> list[dict]:
    outbound = (await db.execute(
        select(OutboundOrder)
        .where(OutboundOrder.id == outbound_order_id)
    )).scalar_one_or_none()
    if outbound is None:
        raise NotFoundError(f"出库单不存在: {outbound_order_id}")
    if outbound.status != OutboundOrderStatus.ISSUED:
        raise CustomerReturnSourceInvalidError("仅已确认出库单可查询客户可退行")
    shipment_status = (await db.execute(
        select(ShipmentOrder.status).where(ShipmentOrder.id == outbound.shipment_id)
    )).scalar_one_or_none()
    if shipment_status not in {ShipmentOrderStatus.LOADED, ShipmentOrderStatus.DEPARTED}:
        raise CustomerReturnSourceInvalidError("柜未封或已取消时不可查询客户可退行")

    rows = (await db.execute(
        select(OutboundOrderLine, SalesOrderLine)
        .join(SalesOrderLine, SalesOrderLine.id == OutboundOrderLine.sales_order_line_id)
        .where(OutboundOrderLine.outbound_order_id == outbound_order_id)
        .order_by(OutboundOrderLine.id)
    )).all()
    returned_qty = await _returned_qty_by_outbound_line(db, [line.id for line, _ in rows])
    result = []
    for outbound_line, sales_line in rows:
        returned = returned_qty[outbound_line.id]
        outbound_qty = Decimal(str(outbound_line.qty))
        result.append({
            "outbound_order_line_id": outbound_line.id,
            "sales_order_line_id": outbound_line.sales_order_line_id,
            "sku_id": outbound_line.sku_id,
            "name_snapshot": sales_line.name_snapshot,
            "spec_text_snapshot": sales_line.spec_text_snapshot,
            "unit_snapshot": sales_line.unit_snapshot,
            "language": sales_line.language,
            "outbound_qty": float(outbound_qty),
            "returned_qty": float(returned),
            "returnable_qty": float(outbound_qty - returned),
        })
    return result
