"""应付款读服务(账层)。P0 只读:列表 + 详情投影。付款/核销 = 财务步。

🔴 整表红线域:端点级 payable:read 门控(见 api/v1/payables.py),不做字段级脱敏。
所有余额/列表聚合一律 WHERE voided_at IS NULL(作废行留痕、不进聚合)。
status(未付/部分付/已付清)派生自 amount_*,不落列(见 payable.derive_payable_status)。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.inbound_order import InboundOrder
from app.db.models.payable import Payable
from app.db.models.purchase_order import PurchaseOrder
from app.db.models.supplier import Supplier


async def list_payables(db: AsyncSession, *, supplier_id=None, currency=None,
                        page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """应付列表(仅活动行):供应商/币种过滤 + 分页,created_at 降序。
    投影供应商名 + 入库单号 + PO 号(人面识别,账层无自身业务号)。"""
    conds = [Payable.voided_at.is_(None)]
    if supplier_id:
        conds.append(Payable.supplier_id == supplier_id)
    if currency:
        conds.append(Payable.currency == currency)

    total = (await db.execute(
        select(func.count(Payable.id)).where(*conds))).scalar_one()
    rows = (await db.execute(
        select(Payable, Supplier.name, InboundOrder.no, PurchaseOrder.no)
        .join(Supplier, Supplier.id == Payable.supplier_id)
        .join(InboundOrder, InboundOrder.id == Payable.inbound_order_id)
        .join(PurchaseOrder, PurchaseOrder.id == Payable.purchase_order_id)
        .where(*conds).order_by(Payable.created_at.desc())
        .offset((page - 1) * size).limit(size))).all()
    items = [{
        "id": p.id, "inbound_order_id": p.inbound_order_id, "inbound_order_no": inb_no,
        "purchase_order_id": p.purchase_order_id, "purchase_order_no": po_no,
        "supplier_id": p.supplier_id, "supplier_display": sup_name, "currency": p.currency,
        "amount_original": p.amount_original, "amount_allocated": p.amount_allocated,
        "balance": p.balance, "due_at": p.due_at, "created_at": p.created_at,
    } for (p, sup_name, inb_no, po_no) in rows]
    return items, total
