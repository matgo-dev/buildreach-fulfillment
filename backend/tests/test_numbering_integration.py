import pytest

from app.core.codegen import NumberScope
from app.services.numbering import allocate


@pytest.mark.asyncio
async def test_allocate_starts_at_one_and_increments(db_session):
    assert await allocate(db_session, NumberScope.SKU) == 1
    assert await allocate(db_session, NumberScope.SKU) == 2


@pytest.mark.asyncio
async def test_scopes_and_periods_are_independent(db_session):
    assert await allocate(db_session, NumberScope.SKU) == 1
    assert await allocate(db_session, NumberScope.CUSTOMER) == 1          # 另一 scope 独立
    assert await allocate(db_session, NumberScope.QUOTATION, "202607") == 1
    assert await allocate(db_session, NumberScope.QUOTATION, "202608") == 1  # 另一年月独立
    assert await allocate(db_session, NumberScope.QUOTATION, "202607") == 2
