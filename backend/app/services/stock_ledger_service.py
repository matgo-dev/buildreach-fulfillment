from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InboundUnreceiveWouldGoNegativeError
from app.db.models.inbound_order import InboundOrderLine
from app.db.models.outbound_order import OutboundOrderLine
from app.db.models.purchase_order import PurchaseOrderLine
from app.db.models.sales_order import SalesOrder, SalesOrderLine
from app.db.models.stock import (
    InventoryBalance,
    InventoryMovement,
    InventoryMovementType,
    InventorySourceType,
)


@dataclass(frozen=True)
class StockImpact:
    sales_order_id: int
    sku_id: int
    source_line_id: int
    qty: Decimal


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def inbound_impacts(db: AsyncSession, inbound_order_id: int) -> list[StockImpact]:
    rows = (await db.execute(
        select(
            SalesOrderLine.sales_order_id,
            InboundOrderLine.sku_id,
            InboundOrderLine.id,
            InboundOrderLine.qty,
        )
        .join(PurchaseOrderLine,
              PurchaseOrderLine.id == InboundOrderLine.purchase_order_line_id)
        .join(SalesOrderLine,
              SalesOrderLine.id == PurchaseOrderLine.source_sales_order_line_id)
        .where(InboundOrderLine.inbound_order_id == inbound_order_id)
        .order_by(SalesOrderLine.sales_order_id, InboundOrderLine.id))).all()
    return [
        StockImpact(
            sales_order_id=so_id,
            sku_id=sku_id,
            source_line_id=line_id,
            qty=Decimal(str(qty)),
        )
        for so_id, sku_id, line_id, qty in rows
    ]


async def outbound_impacts(db: AsyncSession, outbound_order_id: int) -> list[StockImpact]:
    rows = (await db.execute(
        select(
            SalesOrderLine.sales_order_id,
            OutboundOrderLine.sku_id,
            OutboundOrderLine.id,
            OutboundOrderLine.qty,
        )
        .join(SalesOrderLine, SalesOrderLine.id == OutboundOrderLine.sales_order_line_id)
        .where(OutboundOrderLine.outbound_order_id == outbound_order_id)
        .order_by(SalesOrderLine.sales_order_id, OutboundOrderLine.id))).all()
    return [
        StockImpact(
            sales_order_id=so_id,
            sku_id=sku_id,
            source_line_id=line_id,
            qty=Decimal(str(qty)),
        )
        for so_id, sku_id, line_id, qty in rows
    ]


async def lock_sales_orders(db: AsyncSession, sales_order_ids: list[int]) -> None:
    """按 id 升序锁 SO 头,让库存余额写入与出库校验保持同一串行化边界。"""
    for so_id in sorted(set(sales_order_ids)):
        await db.execute(select(SalesOrder).where(SalesOrder.id == so_id).with_for_update())


async def _lock_balance(db: AsyncSession, sales_order_id: int, sku_id: int) -> InventoryBalance:
    balance = (await db.execute(
        select(InventoryBalance)
        .where(
            InventoryBalance.sales_order_id == sales_order_id,
            InventoryBalance.sku_id == sku_id,
        )
        .with_for_update())).scalar_one_or_none()
    if balance is None:
        balance = InventoryBalance(
            sales_order_id=sales_order_id,
            sku_id=sku_id,
            inbound_qty=0,
            outbound_qty=0,
            disposition_qty=0,
        )
        db.add(balance)
        await db.flush()
    return balance


async def _apply_balance_delta(
    db: AsyncSession, *,
    sales_order_id: int,
    sku_id: int,
    inbound_delta: Decimal = Decimal("0"),
    outbound_delta: Decimal = Decimal("0"),
    disposition_delta: Decimal = Decimal("0"),
) -> InventoryBalance:
    balance = await _lock_balance(db, sales_order_id, sku_id)
    inbound_qty = Decimal(str(balance.inbound_qty)) + inbound_delta
    outbound_qty = Decimal(str(balance.outbound_qty)) + outbound_delta
    disposition_qty = Decimal(str(balance.disposition_qty)) + disposition_delta
    balance.inbound_qty = inbound_qty
    balance.outbound_qty = outbound_qty
    balance.disposition_qty = disposition_qty
    await db.flush()
    return balance


async def _record_movement(
    db: AsyncSession, *,
    movement_type: str,
    source_type: str,
    source_id: int,
    source_line_id: int,
    sales_order_id: int,
    sku_id: int,
    qty_delta: Decimal,
    occurred_at: datetime | None,
    created_by: int,
    note: str | None = None,
) -> InventoryMovement:
    movement = InventoryMovement(
        movement_type=movement_type,
        source_type=source_type,
        source_id=source_id,
        source_line_id=source_line_id,
        sales_order_id=sales_order_id,
        sku_id=sku_id,
        qty_delta=qty_delta,
        occurred_at=occurred_at or _utcnow(),
        created_by=created_by,
        note=note,
    )
    db.add(movement)
    return movement


async def record_inbound_receive(
    db: AsyncSession, *,
    inbound_order_id: int,
    occurred_at: datetime | None,
    actor_user_id: int,
) -> None:
    impacts = await inbound_impacts(db, inbound_order_id)
    for impact in impacts:
        await _record_movement(
            db,
            movement_type=InventoryMovementType.INBOUND_RECEIVE,
            source_type=InventorySourceType.INBOUND_ORDER,
            source_id=inbound_order_id,
            source_line_id=impact.source_line_id,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            qty_delta=impact.qty,
            occurred_at=occurred_at,
            created_by=actor_user_id,
        )
        await _apply_balance_delta(
            db,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            inbound_delta=impact.qty,
        )


def _aggregate_by_so_sku(impacts: list[StockImpact]) -> dict[tuple[int, int], Decimal]:
    agg: dict[tuple[int, int], Decimal] = defaultdict(lambda: Decimal("0"))
    for impact in impacts:
        agg[(impact.sales_order_id, impact.sku_id)] += impact.qty
    return dict(agg)


async def assert_can_unreceive_inbound(db: AsyncSession, inbound_order_id: int) -> None:
    impacts = await inbound_impacts(db, inbound_order_id)
    qty_by_key = _aggregate_by_so_sku(impacts)
    negatives = []
    for (so_id, sku_id), qty in qty_by_key.items():
        balance = (await db.execute(
            select(InventoryBalance)
            .where(InventoryBalance.sales_order_id == so_id, InventoryBalance.sku_id == sku_id)
            .with_for_update())).scalar_one_or_none()
        current_available = Decimal(str(balance.available_qty)) if balance else Decimal("0")
        future_available = current_available - qty
        if future_available < 0:
            negatives.append({
                "sales_order_id": so_id,
                "sku_id": sku_id,
                "available_qty": float(future_available),
            })
    if negatives:
        pairs = [(n["sales_order_id"], n["sku_id"]) for n in negatives]
        display = {
            (so_id, sku_id): (so_no, name)
            for so_id, sku_id, so_no, name in (
                await db.execute(
                    select(
                        SalesOrderLine.sales_order_id,
                        SalesOrderLine.sku_id,
                        SalesOrder.no,
                        SalesOrderLine.name_snapshot,
                    )
                    .join(SalesOrder, SalesOrder.id == SalesOrderLine.sales_order_id)
                    .where(
                        tuple_(SalesOrderLine.sales_order_id, SalesOrderLine.sku_id)
                        .in_(pairs)
                    )
                )
            ).all()
        }
        for n in negatives:
            so_no, name = display.get((n["sales_order_id"], n["sku_id"]), ("", ""))
            n["sales_order_no"], n["name_snapshot"] = so_no, name
        raise InboundUnreceiveWouldGoNegativeError(data={"items": negatives})


async def record_inbound_unreceive(
    db: AsyncSession, *,
    inbound_order_id: int,
    actor_user_id: int,
    note: str | None,
) -> None:
    impacts = await inbound_impacts(db, inbound_order_id)
    for impact in impacts:
        await _record_movement(
            db,
            movement_type=InventoryMovementType.INBOUND_UNRECEIVE,
            source_type=InventorySourceType.INBOUND_ORDER,
            source_id=inbound_order_id,
            source_line_id=impact.source_line_id,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            qty_delta=-impact.qty,
            occurred_at=_utcnow(),
            created_by=actor_user_id,
            note=note,
        )
        await _apply_balance_delta(
            db,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            inbound_delta=-impact.qty,
        )


async def record_outbound_issue(
    db: AsyncSession, *,
    outbound_order_id: int,
    occurred_at: datetime | None,
    actor_user_id: int,
) -> None:
    impacts = await outbound_impacts(db, outbound_order_id)
    for impact in impacts:
        await _record_movement(
            db,
            movement_type=InventoryMovementType.OUTBOUND_ISSUE,
            source_type=InventorySourceType.OUTBOUND_ORDER,
            source_id=outbound_order_id,
            source_line_id=impact.source_line_id,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            qty_delta=-impact.qty,
            occurred_at=occurred_at,
            created_by=actor_user_id,
        )
        await _apply_balance_delta(
            db,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            outbound_delta=impact.qty,
        )


async def record_purchase_return_issue(
    db: AsyncSession, *,
    purchase_return_order_id: int,
    impacts: list[StockImpact],
    occurred_at: datetime | None,
    actor_user_id: int,
    note: str | None = None,
) -> None:
    """采购退货出库:扣减销售单维度已入库数量,库存仍不进入自由库存。"""
    for impact in impacts:
        await _record_movement(
            db,
            movement_type=InventoryMovementType.PURCHASE_RETURN_ISSUE,
            source_type=InventorySourceType.PURCHASE_RETURN_ORDER,
            source_id=purchase_return_order_id,
            source_line_id=impact.source_line_id,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            qty_delta=-impact.qty,
            occurred_at=occurred_at,
            created_by=actor_user_id,
            note=note,
        )
        await _apply_balance_delta(
            db,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            inbound_delta=-impact.qty,
        )


async def record_disposition_hold(
    db: AsyncSession, *,
    inventory_disposition_order_id: int,
    impacts: list[StockImpact],
    occurred_at: datetime | None,
    actor_user_id: int,
    note: str | None = None,
) -> None:
    """库存处置:货仍归属原销售单,但转入待处置,不可再被正向出库消费。

    DISPOSITION_HOLD 的 qty_delta 只表达可发库存减少;物理仍在仓时由 balance.inbound_qty
    与 balance.disposition_qty 同时保留,避免把待处置误记成出库事实。
    """
    for impact in impacts:
        await _record_movement(
            db,
            movement_type=InventoryMovementType.DISPOSITION_HOLD,
            source_type=InventorySourceType.INVENTORY_DISPOSITION_ORDER,
            source_id=inventory_disposition_order_id,
            source_line_id=impact.source_line_id,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            qty_delta=-impact.qty,
            occurred_at=occurred_at,
            created_by=actor_user_id,
            note=note,
        )
        await _apply_balance_delta(
            db,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            disposition_delta=impact.qty,
        )


async def record_customer_return_receive(
    db: AsyncSession, *,
    customer_return_order_id: int,
    impacts: list[StockImpact],
    occurred_at: datetime | None,
    actor_user_id: int,
    note: str | None = None,
) -> None:
    """客户退回入售后库存:物理回仓,但同步转待处置,不增加可发库存。"""
    for impact in impacts:
        await _record_movement(
            db,
            movement_type=InventoryMovementType.CUSTOMER_RETURN_RECEIVE,
            source_type=InventorySourceType.CUSTOMER_RETURN_ORDER,
            source_id=customer_return_order_id,
            source_line_id=impact.source_line_id,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            qty_delta=impact.qty,
            occurred_at=occurred_at,
            created_by=actor_user_id,
            note=note,
        )
        await _apply_balance_delta(
            db,
            sales_order_id=impact.sales_order_id,
            sku_id=impact.sku_id,
            inbound_delta=impact.qty,
            disposition_delta=impact.qty,
        )
