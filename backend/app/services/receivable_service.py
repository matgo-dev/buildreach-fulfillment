"""应收款读服务(账层)。P0 只读:列表 + 单查投影。收款/核销 = 财务步(T15)。

🔴 整表红线域(客户售价):端点级 receivable:read 门控(见 api/v1/receivables.py),
不做字段级脱敏。所有余额/列表聚合一律 WHERE voided_at IS NULL(作废行留痕、不进聚合)。
status(未收/部分收/已收清)派生自 amount_*,不落列(receivable.derive_receivable_status)。
"""
from __future__ import annotations

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.customer import Customer
from app.db.models.outbound_order import OutboundOrder
from app.db.models.receipt import Receipt
from app.db.models.receipt_allocation import ReceiptAllocation
from app.db.models.receivable import Receivable, ReceivableStatus, derive_receivable_status
from app.db.models.sales_order import SalesOrder
from app.services.repo import paginate

# 派生状态 → SQL 谓词(**镜像 derive_receivable_status 判序**:先收清含 0 金额单,勿倒序改)。
_STATUS_CONDS = {
    ReceivableStatus.PAID: Receivable.amount_allocated >= Receivable.amount_original,
    ReceivableStatus.UNPAID: (Receivable.amount_allocated <= 0)
    & (Receivable.amount_original > 0),
    ReceivableStatus.PARTIALLY_PAID: (Receivable.amount_allocated > 0)
    & (Receivable.amount_allocated < Receivable.amount_original),
}


async def get(db: AsyncSession, receivable_id: int) -> Receivable | None:
    return (await db.execute(
        select(Receivable).where(Receivable.id == receivable_id))).scalar_one_or_none()


async def list_receivables(db: AsyncSession, *, customer_id=None, status: str | None = None,
                           currency: str | None = None, q: str | None = None,
                           page: int = 1, size: int = 20) -> tuple[list[dict], int]:
    """应收列表(仅活动行):客户/状态/币种/搜索过滤 + 分页,created_at 降序。
    投影客户名 + 出库单号 + SO 号(账层无自身业务号);q = 出库单号 / SO 号 / 客户名 模糊。"""
    conds = [Receivable.voided_at.is_(None)]
    if customer_id:
        conds.append(Receivable.customer_id == customer_id)
    if currency:
        conds.append(Receivable.currency == currency)
    if status in _STATUS_CONDS:
        conds.append(_STATUS_CONDS[status])
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(OutboundOrder.no.ilike(like) | SalesOrder.no.ilike(like)
                     | Customer.name.ilike(like))

    base = (select(Receivable, Customer.name, OutboundOrder.no, SalesOrder.no)
            .join(Customer, Customer.id == Receivable.customer_id)
            .join(OutboundOrder, OutboundOrder.id == Receivable.outbound_order_id)
            .join(SalesOrder, SalesOrder.id == Receivable.sales_order_id)
            .where(*conds))
    rows, total = await paginate(
        db, base.order_by(Receivable.created_at.desc()), page=page, size=size, scalars=False)
    # D10:本页涉及客户中,谁有未分配收款余额(预收)。单条聚合查询(走 receipts.customer_id
    # 索引 + amount_unallocated>0 谓词),按页有界,无 N+1;标志纯提示,不自动核销。
    cust_ids = {r.customer_id for (r, *_rest) in rows}
    unalloc = await _customers_with_unallocated(db, cust_ids)
    items = [{
        "id": r.id, "outbound_order_id": r.outbound_order_id, "outbound_order_no": ob_no,
        "sales_order_id": r.sales_order_id, "sales_order_no": so_no,
        "customer_id": r.customer_id, "customer_display": cust_name, "currency": r.currency,
        "amount_original": r.amount_original, "amount_allocated": r.amount_allocated,
        "balance": r.balance, "due_at": r.due_at, "created_at": r.created_at,
        "counterparty_has_unallocated": r.customer_id in unalloc,
    } for (r, cust_name, ob_no, so_no) in rows]
    return items, total


async def _customers_with_unallocated(db: AsyncSession, customer_ids: set[int]) -> set[int]:
    if not customer_ids:
        return set()
    return set((await db.execute(
        select(distinct(Receipt.customer_id)).where(
            Receipt.customer_id.in_(customer_ids),
            Receipt.voided_at.is_(None),
            Receipt.amount_unallocated > 0))).scalars().all())


async def get_detail(db: AsyncSession, receivable_id: int) -> dict:
    """应收款详情:账头 + 活动核销记录(哪笔收款冲了多少、何时、操作人),供「怎么收清的」追溯。"""
    r = await get(db, receivable_id)
    if r is None:
        raise NotFoundError(f"应收款不存在: {receivable_id}")
    rows = (await db.execute(
        select(ReceiptAllocation, Receipt.receipt_no)
        .join(Receipt, Receipt.id == ReceiptAllocation.receipt_id)
        .where(ReceiptAllocation.receivable_id == receivable_id,
               ReceiptAllocation.reversed_at.is_(None))
        .order_by(ReceiptAllocation.id))).all()
    cust_name = (await db.execute(
        select(Customer.name).where(Customer.id == r.customer_id))).scalar_one_or_none()
    ob_no = (await db.execute(
        select(OutboundOrder.no).where(OutboundOrder.id == r.outbound_order_id))).scalar_one()
    return {
        "id": r.id, "outbound_order_id": r.outbound_order_id, "outbound_order_no": ob_no,
        "sales_order_id": r.sales_order_id, "customer_id": r.customer_id,
        "customer_display": cust_name, "currency": r.currency,
        "amount_original": float(r.amount_original), "amount_allocated": float(r.amount_allocated),
        "balance": float(r.balance), "due_at": r.due_at,
        "status": derive_receivable_status(r.amount_original, r.amount_allocated),
        "created_at": r.created_at,
        "allocations": [{
            "id": a.id, "receipt_id": a.receipt_id, "receipt_no": rc_no,
            "amount": float(a.amount), "alloc_type": a.alloc_type, "created_at": a.created_at,
        } for a, rc_no in rows],
    }
