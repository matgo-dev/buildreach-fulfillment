"""采购单状态机矩阵单测(轴1 单据生命周期,model 层单一源头)。

DRAFT→CONFIRMED(下单)→CANCELLED;DRAFT 可直接取消;CANCELLED 终态无出边。
可编辑/可硬删仅 DRAFT。不设 SENT;RECEIVED 留入库步。
"""
from app.db.models.purchase_order import (
    PURCHASE_ORDER_DELETABLE_STATUSES,
    PURCHASE_ORDER_EDITABLE_STATUSES,
    PURCHASE_ORDER_TRANSITIONS,
    PurchaseOrderStatus,
)


def test_draft_can_confirm_or_cancel():
    assert PURCHASE_ORDER_TRANSITIONS[PurchaseOrderStatus.DRAFT] == {
        PurchaseOrderStatus.CONFIRMED, PurchaseOrderStatus.CANCELLED}


def test_confirmed_can_only_cancel():
    assert PURCHASE_ORDER_TRANSITIONS[PurchaseOrderStatus.CONFIRMED] == {
        PurchaseOrderStatus.CANCELLED}


def test_cancelled_is_terminal():
    assert PURCHASE_ORDER_TRANSITIONS[PurchaseOrderStatus.CANCELLED] == set()


def test_only_draft_editable_and_deletable():
    assert PURCHASE_ORDER_EDITABLE_STATUSES == {PurchaseOrderStatus.DRAFT}
    assert PURCHASE_ORDER_DELETABLE_STATUSES == {PurchaseOrderStatus.DRAFT}


def test_no_confirmed_to_draft_backdoor():
    """CONFIRMED 已下单,不可回退草稿(与报价的 LOCKED→DRAFT 故意不同:下单不可撤回,只能取消)。"""
    assert PurchaseOrderStatus.DRAFT not in PURCHASE_ORDER_TRANSITIONS[PurchaseOrderStatus.CONFIRMED]


def test_status_all_matches_matrix_keys():
    """状态全集与转移矩阵键一致(单一源头无遗漏)。"""
    assert set(PurchaseOrderStatus.ALL) == set(PURCHASE_ORDER_TRANSITIONS.keys())
