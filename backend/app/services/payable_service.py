"""应付款读服务(账层)。P0 只读:列表 + 详情投影。付款/核销 = 财务步。

🔴 整表红线域:端点级 payable:read 门控(见 api/v1/payables.py),不做字段级脱敏。
所有未结应付/列表聚合一律 WHERE voided_at IS NULL(作废行留痕、不进聚合)。
status(未付/部分付/已付清)派生自 amount_*,不落列(见 payable.derive_payable_status)。
"""
from __future__ import annotations

from sqlalchemy import distinct, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.models.inbound_order import InboundOrder
from app.db.models._settlement import (
    is_fully_settled,
    is_partially_settled,
    is_unsettled,
)
from app.db.models.payable import Payable, PayableStatus, derive_payable_status
from app.db.models.payment import Payment
from app.db.models.payment_allocation import PaymentAllocation
from app.db.models.purchase_order import PurchaseOrder
from app.db.models.supplier import Supplier
from app.services.repo import paginate

# 派生状态 → SQL 谓词(边界共用 _settlement,与 derive_payable_status 同源不双写)。
_PAYABLE_EFFECTIVE_TOTAL = Payable.amount_original - Payable.amount_credited
_STATUS_CONDS = {
    PayableStatus.PAID: is_fully_settled(_PAYABLE_EFFECTIVE_TOTAL, Payable.amount_allocated),
    PayableStatus.UNPAID: is_unsettled(_PAYABLE_EFFECTIVE_TOTAL, Payable.amount_allocated),
    PayableStatus.PARTIALLY_PAID: is_partially_settled(
        _PAYABLE_EFFECTIVE_TOTAL, Payable.amount_allocated),
}


async def list_payables(db: AsyncSession, *, supplier_id=None, currency=None,
                        status: str | None = None, q: str | None = None,
                        page: int = 1, size: int = 20,
                        can_read_payment: bool = False) -> tuple[list[dict], int]:
    """应付列表(仅活动行):状态/搜索/供应商/币种过滤 + 分页,created_at 降序。
    投影供应商名 + 入库单号 + PO 号(人面识别,账层无自身业务号)。
    q = 入库单号 / PO 号 / 供应商名 模糊;count 与 rows 同一 join 基座(搜索条件跨表)。"""
    conds = [Payable.voided_at.is_(None)]
    if supplier_id:
        conds.append(Payable.supplier_id == supplier_id)
    if currency:
        conds.append(Payable.currency == currency)
    if status in _STATUS_CONDS:
        conds.append(_STATUS_CONDS[status])
    if q and q.strip():
        like = f"%{q.strip()}%"
        conds.append(or_(InboundOrder.no.ilike(like), PurchaseOrder.no.ilike(like),
                         Supplier.name.ilike(like)))

    base = (select(Payable, Supplier.name, InboundOrder.no, PurchaseOrder.no)
            .join(Supplier, Supplier.id == Payable.supplier_id)
            .join(InboundOrder, InboundOrder.id == Payable.inbound_order_id)
            .join(PurchaseOrder, PurchaseOrder.id == Payable.purchase_order_id)
            .where(*conds))
    # count 走 paginate 缺省口径(去排序后包子查询),与原 select_from(base.subquery()) 同形。
    rows, total = await paginate(
        db, base.order_by(Payable.created_at.desc()),
        page=page, size=size, scalars=False)
    # D10:本页涉及供应商中,谁有未分配付款(预付)。单条聚合查询,按页有界,无 N+1。
    # 🔴 提示位派生自付款域:无 payment:read 不计算不下发(恒 False),权限跟数据走。
    sup_ids = {p.supplier_id for (p, *_rest) in rows} if can_read_payment else set()
    unalloc = await _suppliers_with_unallocated(db, sup_ids)
    items = [{
        "id": p.id, "inbound_order_id": p.inbound_order_id, "inbound_order_no": inb_no,
        "purchase_order_id": p.purchase_order_id, "purchase_order_no": po_no,
        "supplier_id": p.supplier_id, "supplier_display": sup_name, "currency": p.currency,
        "amount_original": p.amount_original, "amount_credited": p.amount_credited,
        "amount_allocated": p.amount_allocated,
        "amount_outstanding": p.amount_outstanding,
        "due_at": p.due_at, "created_at": p.created_at,
        "counterparty_has_unallocated": p.supplier_id in unalloc,
    } for (p, sup_name, inb_no, po_no) in rows]
    return items, total


async def _suppliers_with_unallocated(db: AsyncSession, supplier_ids: set[int]) -> set[int]:
    if not supplier_ids:
        return set()
    return set((await db.execute(
        select(distinct(Payment.supplier_id)).where(
            Payment.supplier_id.in_(supplier_ids),
            Payment.voided_at.is_(None),
            Payment.amount_unallocated > 0))).scalars().all())


async def get(db: AsyncSession, payable_id: int) -> Payable | None:
    return (await db.execute(
        select(Payable).where(Payable.id == payable_id))).scalar_one_or_none()


async def get_detail(db: AsyncSession, payable_id: int, *, can_read_payment: bool) -> dict:
    """应付款详情:账头 + 活动核销记录(哪笔付款冲了多少、何时),供「怎么付清的」追溯。🔴红线。

    核销记录属付款域(红线):无 payment:read 者整块不下发(空列表),与列表提示位同源门控
    ——不该经账层详情旁路感知付款单存在性。账头(已贷记/未结应付/状态)是账层信息,payable:read 即可见。"""
    p = await get(db, payable_id)
    if p is None:
        raise NotFoundError(f"应付款不存在: {payable_id}")
    rows = (await db.execute(
        select(PaymentAllocation, Payment.payment_no)
        .join(Payment, Payment.id == PaymentAllocation.payment_id)
        .where(PaymentAllocation.payable_id == payable_id,
               PaymentAllocation.reversed_at.is_(None))
        .order_by(PaymentAllocation.id))).all() if can_read_payment else []
    sup_name = (await db.execute(
        select(Supplier.name).where(Supplier.id == p.supplier_id))).scalar_one_or_none()
    inb_no = (await db.execute(
        select(InboundOrder.no).where(InboundOrder.id == p.inbound_order_id))).scalar_one()
    return {
        "id": p.id, "inbound_order_id": p.inbound_order_id, "inbound_order_no": inb_no,
        "purchase_order_id": p.purchase_order_id, "supplier_id": p.supplier_id,
        "supplier_display": sup_name, "currency": p.currency,
        "amount_original": float(p.amount_original),
        "amount_credited": float(p.amount_credited),
        "amount_allocated": float(p.amount_allocated),
        "amount_outstanding": float(p.amount_outstanding), "due_at": p.due_at,
        "status": derive_payable_status(p.amount_original, p.amount_allocated, p.amount_credited),
        "created_at": p.created_at,
        "allocations": [{
            "id": a.id, "payment_id": a.payment_id, "payment_no": pm_no,
            "amount": float(a.amount), "alloc_type": a.alloc_type, "created_at": a.created_at,
        } for a, pm_no in rows],
    }
