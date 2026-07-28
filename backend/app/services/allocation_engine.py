"""核销引擎(收付泛型共用)。receipts/payments↔receivables/payables 是收付镜像,
一套算法参数化跑两侧:自动核销(按账龄 FIFO)/ 人工核销(选账取满)/ 反核销(软删留痕)。

单一写入口:全系统 `amount_allocated` 仅由本引擎写(核销 +=,反核销 -=);account.balance /
source.amount_unallocated 由 DB Computed 跟随,不手写。全程 Decimal(两侧 Numeric 取出即
Decimal,min/加减不落 float)。

并发(调用方负责):写入口先锁 source 行(receipt/payment)FOR UPDATE,再由本引擎锁候选账行
(自动核销:取账龄有序 id 后逐行 FOR UPDATE)/ 指定账行(人工/反核销)。锁序钉死「源行先、账行后」,
自动核销多账行按 (due_at, created_at, id) 固定序——无反序路径,无死锁环。偏唯一
uq_*_alloc_active 兜底并发重复核销(冲突转 409,调用方 commit 处映射)。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AccountVoidedCannotAllocateError,
    AllocationCounterpartyMismatchError,
    AllocationCurrencyMismatchError,
    AllocationExceedsAccountError,
    AllocationExceedsSourceError,
    AllocationPairAlreadyActiveError,
    AllocationReverseNotFoundError,
    NotFoundError,
)
from app.db.models.payable import Payable
from app.db.models.payment import Payment
from app.db.models.payment_allocation import PaymentAllocation
from app.db.models.receipt import Receipt
from app.db.models.receipt_allocation import AllocationType, ReceiptAllocation
from app.db.models.receivable import Receivable


@dataclass(frozen=True)
class AllocationSpec:
    """收 / 付一侧的镜像配置(模型 + 关联列 + 对手方列)。收付各一实例,引擎按此泛化。"""
    source_model: type          # Receipt / Payment
    account_model: type         # Receivable / Payable
    alloc_model: type           # ReceiptAllocation / PaymentAllocation
    source_fk: str              # 核销行指向 source 的列名(receipt_id / payment_id)
    account_fk: str             # 核销行指向 account 的列名(receivable_id / payable_id)
    party_source_attr: str      # source 对手方列(customer_id / supplier_id)
    party_account_attr: str     # account 对手方列(customer_id / supplier_id)


RECEIPT_SPEC = AllocationSpec(
    source_model=Receipt, account_model=Receivable, alloc_model=ReceiptAllocation,
    source_fk="receipt_id", account_fk="receivable_id",
    party_source_attr="customer_id", party_account_attr="customer_id")

PAYMENT_SPEC = AllocationSpec(
    source_model=Payment, account_model=Payable, alloc_model=PaymentAllocation,
    source_fk="payment_id", account_fk="payable_id",
    party_source_attr="supplier_id", party_account_attr="supplier_id")


def _d(x) -> Decimal:
    return Decimal(str(x))


def _source_remaining(source) -> Decimal:
    return _d(source.amount) - _d(source.amount_allocated)


def _account_balance(account) -> Decimal:
    return _d(account.amount_original) - _d(account.amount_allocated)


async def lock_source(db: AsyncSession, spec: AllocationSpec, source_id: int):
    """锁 source 行 FOR UPDATE(写入口统一前置,锁序最先)。"""
    return (await db.execute(
        select(spec.source_model).where(spec.source_model.id == source_id)
        .with_for_update())).scalar_one()


async def active_allocations(db: AsyncSession, spec: AllocationSpec, source_id: int) -> list:
    """某 source 的活动核销记录(reversed_at IS NULL),按 id 正序。详情/审计用。"""
    m = spec.alloc_model
    return list((await db.execute(
        select(m).where(getattr(m, spec.source_fk) == source_id, m.reversed_at.is_(None))
        .order_by(m.id))).scalars().all())


async def has_active_allocations(db: AsyncSession, spec: AllocationSpec, source_id: int) -> bool:
    m = spec.alloc_model
    return (await db.execute(
        select(m.id).where(getattr(m, spec.source_fk) == source_id, m.reversed_at.is_(None))
        .limit(1))).scalar_one_or_none() is not None


async def auto_allocate(db: AsyncSession, spec: AllocationSpec, source, *,
                        actor_user_id: int) -> list:
    """自动核销:按账龄 FIFO 冲开口账,取满 min(source 未分配, 账余额),多余留存(预收/预付)。
    调用方须已锁 source 行 FOR UPDATE。source 未认领(对手方空)/ 无未分配余额 → 不核销。

    锁法:先按 (due_at NULLS LAST, created_at, id) 取有序候选 id(不加锁),再逐行 FOR UPDATE
    ——与采购/入库「取有序 id 再逐行锁」同一显式范式,锁序=取序,不依赖「ORDER BY ... FOR UPDATE」
    的计划相关锁序。锁后复核(账未作废、仍有余额)顶替裸 SELECT 的 EvalPlanQual;累计已锁余额够冲
    remaining 即停,不多锁尾部无关账行。"""
    party = getattr(source, spec.party_source_attr)
    if party is None:
        return []
    remaining = _source_remaining(source)
    if remaining <= 0:
        return []
    A = spec.account_model
    ordered_ids = (await db.execute(
        select(A.id).where(
            getattr(A, spec.party_account_attr) == party,
            A.currency == source.currency,
            A.voided_at.is_(None),
            A.balance > 0)
        .order_by(A.due_at.asc().nullslast(), A.created_at.asc(), A.id.asc()))).scalars().all()
    locked = []
    need = remaining
    for acc_id in ordered_ids:
        if need <= 0:
            break
        acc = (await db.execute(
            select(A).where(A.id == acc_id).with_for_update())).scalar_one_or_none()
        # 锁后复核:取序无锁,并发可能已把该账作废/核满(裸 FOR UPDATE 的 EvalPlanQual 手动版)。
        if acc is None or acc.voided_at is not None or _account_balance(acc) <= 0:
            continue
        locked.append(acc)
        need -= _account_balance(acc)
    return await _apply(db, spec, source, locked, remaining,
                        alloc_type=AllocationType.AUTO, actor_user_id=actor_user_id)


async def _apply(db, spec, source, accounts, remaining: Decimal, *, alloc_type: str,
                 actor_user_id: int) -> list:
    created = []
    for acc in accounts:
        if remaining <= 0:
            break
        take = min(remaining, _account_balance(acc))
        if take <= 0:
            continue
        alloc = spec.alloc_model(**{spec.source_fk: source.id, spec.account_fk: acc.id},
                                 amount=take, alloc_type=alloc_type, created_by=actor_user_id)
        db.add(alloc)
        source.amount_allocated = _d(source.amount_allocated) + take
        acc.amount_allocated = _d(acc.amount_allocated) + take
        remaining -= take
        created.append(alloc)
    await db.flush()
    return created


async def manual_allocate(db: AsyncSession, spec: AllocationSpec, source, account_id: int, *,
                          actor_user_id: int):
    """人工核销:指定账,核销额强制取满 min(source 未分配, 账余额),不允许自填欠额(D8)。
    调用方须已锁 source 行。本函数锁指定账行 FOR UPDATE 并校验:同对手方、同币种、账未作废、
    同对无活动核销(42210)、双侧有余额。偏唯一兜底并发写(调用方映射同 42210)。"""
    A = spec.account_model
    acc = (await db.execute(
        select(A).where(A.id == account_id).with_for_update())).scalar_one_or_none()
    if acc is None:
        raise NotFoundError(f"账不存在: {account_id}")
    if acc.voided_at is not None:
        raise AccountVoidedCannotAllocateError()
    if getattr(acc, spec.party_account_attr) != getattr(source, spec.party_source_attr):
        raise AllocationCounterpartyMismatchError()
    if acc.currency != source.currency:
        raise AllocationCurrencyMismatchError()
    # 同 (source, account) 已有活动核销 → 42210(偏唯一契约:一对至多一条,部分核销靠 amount)。
    # 单线程可达:反核销其它账后 source 回血、同对余额也 >0,重核同对即撞;source+account 双锁下
    # 判定无 TOCTOU,偏唯一仅兜底并发。前置判而非等 IntegrityError,错误语义才准确(非「超余额」)。
    am = spec.alloc_model
    dup = (await db.execute(
        select(am.id).where(getattr(am, spec.source_fk) == source.id,
                            getattr(am, spec.account_fk) == account_id,
                            am.reversed_at.is_(None)).limit(1))).scalar_one_or_none()
    if dup is not None:
        raise AllocationPairAlreadyActiveError()
    remaining = _source_remaining(source)
    if remaining <= 0:
        raise AllocationExceedsSourceError()
    if _account_balance(acc) <= 0:
        raise AllocationExceedsAccountError()
    created = await _apply(db, spec, source, [acc], remaining,
                           alloc_type=AllocationType.MANUAL, actor_user_id=actor_user_id)
    return created[0]


async def reverse(db: AsyncSession, spec: AllocationSpec, alloc_id: int, *,
                  actor_user_id: int, reason: str | None):
    """反核销:软删该核销记录(reversed_at 留痕),金额退回 source 未分配 + 账余额恢复。
    已反核销/不存在 → 42205(幂等)。

    并发正确性 = 「首锁即读」(与登录行锁/D2 撤账守卫同模式):alloc 行在本 session 的
    **首次加载即带 FOR UPDATE**——并发双反核销时后到者阻塞于行锁,解锁后首读即见
    reversed_at 非空 → 42205。不可先裸读、锁后再重读:SQLAlchemy identity map 对已加载
    对象默认**丢弃重读的新行值**(需 populate_existing 才覆盖),锁后重判会恒真、形同虚设。
    锁序:alloc → source → account;核销路径只 INSERT 新 alloc 行、从不锁既有 alloc 行,
    无反向持锁,无死锁环。
    """
    from datetime import datetime, timezone
    m = spec.alloc_model
    alloc = (await db.execute(
        select(m).where(m.id == alloc_id).with_for_update())).scalar_one_or_none()
    if alloc is None or alloc.reversed_at is not None:
        raise AllocationReverseNotFoundError()
    # 锁序:source 行先、account 行后(与核销写入口同向,无环)。
    source = await lock_source(db, spec, getattr(alloc, spec.source_fk))
    acc = (await db.execute(
        select(spec.account_model).where(spec.account_model.id == getattr(alloc, spec.account_fk))
        .with_for_update())).scalar_one()
    amt = _d(alloc.amount)
    alloc.reversed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    alloc.reversed_by = actor_user_id
    alloc.reverse_reason = reason
    source.amount_allocated = _d(source.amount_allocated) - amt
    acc.amount_allocated = _d(acc.amount_allocated) - amt
    await db.flush()
    return alloc, source, acc
