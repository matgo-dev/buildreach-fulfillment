"""统一业务编号服务(SAP/Odoo 口径:号段由编号服务发放,不拼主键)。

- 主数据(SKU/CUSTOMER):全局号段(period=''),中性不透明、不承载可变业务含义。
- 单据(QUOTATION 及后续 SO/PO/IN/OUT/SH):按单据类型 + 年月号段,便于人工识别/归档/降跨期冲突。
并发安全:INSERT ... ON CONFLICT DO UPDATE RETURNING 原子自增(gapless-from-1;内部低并发,行锁足够)。
"""
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.number_sequence import NumberSequence


class NumberScope:
    SKU = "SKU"
    CUSTOMER = "CUSTOMER"
    QUOTATION = "QUOTATION"


async def allocate(db: AsyncSession, scope: str, period: str = "") -> int:
    """发一个号段内的下一个序号(从 1 起,原子自增)。"""
    stmt = (
        insert(NumberSequence)
        .values(scope=scope, period=period, next_seq=1)
        .on_conflict_do_update(
            index_elements=["scope", "period"],
            set_={"next_seq": NumberSequence.next_seq + 1},
        )
        .returning(NumberSequence.next_seq)
    )
    return (await db.execute(stmt)).scalar_one()
