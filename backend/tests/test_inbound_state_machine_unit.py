"""入库状态机矩阵(锚点 5):合法/非法转移、编辑集、无硬删。纯常量,无 DB。"""
from app.db.models.inbound_order import (
    INBOUND_ORDER_DELETABLE_STATUSES,
    INBOUND_ORDER_EDITABLE_STATUSES,
    INBOUND_ORDER_TRANSITIONS,
    InboundOrderStatus,
)


def test_transitions_matrix():
    S = InboundOrderStatus
    assert INBOUND_ORDER_TRANSITIONS[S.IN_TRANSIT] == {S.RECEIVED, S.CANCELLED}
    assert INBOUND_ORDER_TRANSITIONS[S.RECEIVED] == {S.IN_TRANSIT}   # 撤销入库
    assert INBOUND_ORDER_TRANSITIONS[S.CANCELLED] == set()           # 终态


def test_editable_only_in_transit():
    assert INBOUND_ORDER_EDITABLE_STATUSES == {InboundOrderStatus.IN_TRANSIT}


def test_no_hard_delete():
    assert INBOUND_ORDER_DELETABLE_STATUSES == set()


def test_status_all_covers_matrix():
    assert set(InboundOrderStatus.ALL) == set(INBOUND_ORDER_TRANSITIONS.keys())
