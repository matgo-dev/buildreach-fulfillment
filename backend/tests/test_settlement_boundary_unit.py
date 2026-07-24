"""结算三态单一边界口径(_settlement)单测。

派生输出(model.derive_*)与 SQL 过滤(service._STATUS_CONDS)现共用这一份边界,
此处锁住边界语义:三态互斥且完备、0 金额单据归 FULL(payment/receipt 曾漏的守卫)。
"""
from decimal import Decimal

import pytest

from app.db.models._settlement import (
    is_fully_settled,
    is_partially_settled,
    is_unsettled,
)

# (total, allocated) → 期望三态 之一:"FULL" / "PARTIAL" / "NONE"
_CASES = [
    ((10, 10), "FULL"),      # 恰好结清
    ((10, 12), "FULL"),      # 超额(核销/退款边界)也算结清
    ((10, 0), "NONE"),       # 全未结
    ((10, 4), "PARTIAL"),    # 部分
    ((0, 0), "FULL"),        # 🔴 0 金额单据:余额 0 即结清,不落 NONE
]


@pytest.mark.parametrize("amounts,expected", _CASES)
def test_tristate_mutually_exclusive_and_complete(amounts, expected):
    total, allocated = Decimal(str(amounts[0])), Decimal(str(amounts[1]))
    flags = {
        "FULL": bool(is_fully_settled(total, allocated)),
        "PARTIAL": bool(is_partially_settled(total, allocated)),
        "NONE": bool(is_unsettled(total, allocated)),
    }
    # 恰好命中一个态(互斥且完备)。
    assert sum(flags.values()) == 1, f"{amounts} 命中 {flags},非唯一"
    assert flags[expected], f"{amounts} 期望 {expected},实得 {flags}"


def test_zero_amount_is_not_unsettled():
    """0 金额单据(total=0)绝不判为「未结」——这是 payment/receipt SQL 曾漏的守卫。"""
    assert not is_unsettled(Decimal("0"), Decimal("0"))
    assert is_fully_settled(Decimal("0"), Decimal("0"))
