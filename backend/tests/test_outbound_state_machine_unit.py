"""出库/柜状态机矩阵 + 应收派生边界。纯常量/纯函数,无 DB。"""
from decimal import Decimal

from app.db.models.outbound_order import (
    OUTBOUND_ORDER_EDITABLE_STATUSES,
    OUTBOUND_ORDER_TRANSITIONS,
    OutboundOrderStatus,
)
from app.db.models.receivable import ReceivableStatus, derive_receivable_status
from app.db.models.shipment_order import (
    SHIPMENT_ORDER_EDITABLE_STATUSES,
    SHIPMENT_ORDER_TRANSITIONS,
    ShipmentOrderStatus,
)


def test_outbound_transitions_matrix():
    S = OutboundOrderStatus
    assert OUTBOUND_ORDER_TRANSITIONS[S.DRAFT] == {S.ISSUED, S.CANCELLED}
    assert OUTBOUND_ORDER_TRANSITIONS[S.ISSUED] == {S.DRAFT}   # 撤销出库
    assert OUTBOUND_ORDER_TRANSITIONS[S.CANCELLED] == set()    # 终态


def test_outbound_editable_only_draft():
    assert OUTBOUND_ORDER_EDITABLE_STATUSES == {OutboundOrderStatus.DRAFT}


def test_outbound_status_all_covers_matrix():
    assert set(OutboundOrderStatus.ALL) == set(OUTBOUND_ORDER_TRANSITIONS.keys())


def test_shipment_transitions_matrix():
    S = ShipmentOrderStatus
    assert SHIPMENT_ORDER_TRANSITIONS[S.OPEN] == {S.CANCELLED}
    assert SHIPMENT_ORDER_TRANSITIONS[S.CANCELLED] == set()


def test_shipment_editable_only_open():
    assert SHIPMENT_ORDER_EDITABLE_STATUSES == {ShipmentOrderStatus.OPEN}


def test_shipment_status_all_covers_matrix():
    assert set(ShipmentOrderStatus.ALL) == set(SHIPMENT_ORDER_TRANSITIONS.keys())


def test_derive_receivable_status_boundaries():
    """0 金额应收(SO 行 unit_price=0 合法)余额 0 = 已收清,不是永远「未收」。"""
    assert derive_receivable_status(0, 0) == ReceivableStatus.PAID
    assert derive_receivable_status(Decimal("5.00"), 0) == ReceivableStatus.UNPAID
    assert derive_receivable_status(Decimal("5.00"), Decimal("2.50")) == \
        ReceivableStatus.PARTIALLY_PAID
    assert derive_receivable_status(Decimal("5.00"), Decimal("5.00")) == ReceivableStatus.PAID
