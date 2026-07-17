"""单据状态机通用守卫(执行代码单点)。

各域转移矩阵(QUOTATION_TRANSITIONS / PURCHASE_ORDER_TRANSITIONS / INBOUND_ORDER_TRANSITIONS /
SALES_ORDER_TRANSITIONS)仍由各 model 层承载单一源头,此处只收敛"查矩阵→抛该域错误"的同构执行,
错误类由调用方按域传入,不合并语义。
"""
from __future__ import annotations

from typing import Mapping


def assert_transition(matrix: Mapping[str, set[str]], current: str, target: str,
                      error_cls: type[Exception]) -> None:
    """合法转移守卫:target ∉ matrix[current] → 抛该域 error_cls(消息格式与各域原状一致)。"""
    if target not in matrix[current]:
        raise error_cls(f"非法转移: {current} → {target}")
