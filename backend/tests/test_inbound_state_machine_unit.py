"""入库状态机矩阵(锚点 5):合法/非法转移、编辑集、无硬删。纯常量/纯函数,无 DB。"""
from app.db.models.inbound_order import (
    INBOUND_ORDER_DELETABLE_STATUSES,
    INBOUND_ORDER_EDITABLE_STATUSES,
    INBOUND_ORDER_TRANSITIONS,
    InboundOrderStatus,
)
from app.db.models.payable import PayableStatus, derive_payable_status


def test_transitions_matrix():
    S = InboundOrderStatus
    assert INBOUND_ORDER_TRANSITIONS[S.IN_TRANSIT] == {S.RECEIVED, S.CANCELLED}
    assert INBOUND_ORDER_TRANSITIONS[S.RECEIVED] == {S.IN_TRANSIT}   # 撤销入库
    assert INBOUND_ORDER_TRANSITIONS[S.CANCELLED] == set()           # 历史/未来逆向终态


def test_no_direct_edit_after_inbound_created():
    assert INBOUND_ORDER_EDITABLE_STATUSES == set()


def test_no_hard_delete():
    assert INBOUND_ORDER_DELETABLE_STATUSES == set()


def test_status_all_covers_matrix():
    assert set(InboundOrderStatus.ALL) == set(INBOUND_ORDER_TRANSITIONS.keys())


def test_derive_payable_status_boundaries():
    """派生函数边界值枚举:0 金额单据余额为 0 = 已付清,不是永远「未付」。"""
    assert derive_payable_status(0, 0) == PayableStatus.PAID          # 0 价 PO(合法)→ 无欠款
    assert derive_payable_status("5.00", 0) == PayableStatus.UNPAID
    assert derive_payable_status("5.00", "2.50") == PayableStatus.PARTIALLY_PAID
    assert derive_payable_status("5.00", "5.00") == PayableStatus.PAID
