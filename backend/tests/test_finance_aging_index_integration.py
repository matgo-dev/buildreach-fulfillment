"""F1(§6):自动核销账龄候选查询命中 partial composite 索引 —— 不走全表扫、不做内存排序。

核销引擎候选查询形状 = WHERE 对手方 + 币种 + voided_at IS NULL + 未结金额 > 0
ORDER BY due_at NULLS LAST, created_at, id。唯一能同时服务「过滤 + 账龄序」且排除已结清行的,
是 ix_*_open_aging(customer/supplier, currency, due_at, created_at, id) WHERE voided_at IS NULL
AND 未结金额 > 0。断言:无 Seq Scan(不全表扫)且无 Sort(排序走进索引)——两者共同锁定该索引被用。

小表上 PG 默认可能 seq scan(数据少更便宜),故 SET LOCAL enable_seqscan=off 让规划器
在「可用索引」中择优,验证索引对该查询形状可用且覆盖排序(结构正确性,非数据规模断言)。
"""
import pytest
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def _plan(db_session, sql: str) -> str:
    await db_session.execute(text("SET LOCAL enable_seqscan = off"))
    rows = (await db_session.execute(text("EXPLAIN " + sql))).all()
    return "\n".join(r[0] for r in rows)


async def test_receivable_aging_query_hits_partial_index(db_session):
    plan = await _plan(db_session,
        "SELECT id FROM receivables "
        "WHERE customer_id = 1 AND currency = 'USD' "
        "AND voided_at IS NULL AND amount_outstanding > 0 "
        "ORDER BY due_at ASC NULLS LAST, created_at ASC, id ASC")
    assert "Seq Scan" not in plan, plan          # 不全表扫
    assert "Sort" not in plan, plan               # 排序走进索引,无内存排序
    assert "ix_receivables_open_aging" in plan, plan


async def test_payable_aging_query_hits_partial_index(db_session):
    plan = await _plan(db_session,
        "SELECT id FROM payables "
        "WHERE supplier_id = 1 AND currency = 'USD' "
        "AND voided_at IS NULL AND amount_outstanding > 0 "
        "ORDER BY due_at ASC NULLS LAST, created_at ASC, id ASC")
    assert "Seq Scan" not in plan, plan
    assert "Sort" not in plan, plan
    assert "ix_payables_open_aging" in plan, plan
