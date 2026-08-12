"""出库/柜状态机矩阵 + 应收派生边界。纯常量/纯函数,无 DB。"""
from decimal import Decimal

from app.db.models.outbound_order import (
    OUTBOUND_ORDER_EDITABLE_STATUSES,
    OUTBOUND_ORDER_TRANSITIONS,
    OutboundOrderStatus,
)
from app.db.models.receivable import ReceivableStatus, derive_receivable_status
from app.db.models.shipment_order import (
    SHIPMENT_EDITABLE_FIELDS_BY_STATUS,
    SHIPMENT_ORDER_TRANSITIONS,
    ShipmentOrderStatus,
)


def test_outbound_transitions_matrix():
    S = OutboundOrderStatus
    assert OUTBOUND_ORDER_TRANSITIONS[S.DRAFT] == {S.ISSUED, S.CANCELLED}
    assert OUTBOUND_ORDER_TRANSITIONS[S.ISSUED] == set()       # 已出库为正向终点
    assert OUTBOUND_ORDER_TRANSITIONS[S.CANCELLED] == set()    # 终态


def test_outbound_editable_only_draft():
    assert OUTBOUND_ORDER_EDITABLE_STATUSES == {OutboundOrderStatus.DRAFT}


def test_outbound_status_all_covers_matrix():
    assert set(OutboundOrderStatus.ALL) == set(OUTBOUND_ORDER_TRANSITIONS.keys())


def test_shipment_transitions_matrix():
    S = ShipmentOrderStatus
    assert SHIPMENT_ORDER_TRANSITIONS[S.OPEN] == {S.LOADED, S.CANCELLED}
    assert SHIPMENT_ORDER_TRANSITIONS[S.LOADED] == {S.DEPARTED, S.OPEN}   # 撤封柜纠错口
    assert SHIPMENT_ORDER_TRANSITIONS[S.DEPARTED] == {S.LOADED}           # 撤离港纠错口
    assert SHIPMENT_ORDER_TRANSITIONS[S.CANCELLED] == set()               # 终态


def test_shipment_editable_fields_by_status():
    """编辑门禁单一源头(按状态给字段集):OPEN 全开、LOADED 锁柜物理组、
    DEPARTED 仅补录组、CANCELLED 空。"""
    F = SHIPMENT_EDITABLE_FIELDS_BY_STATUS
    S = ShipmentOrderStatus
    container = {"container_no", "container_type", "seal_no"}
    shipping = {"booking_no", "vessel_name", "voyage_no", "bl_no",
                "etd", "eta", "port_of_loading", "port_of_discharge"}
    assert F[S.OPEN] == container | shipping | {"note"}
    assert F[S.LOADED] == shipping | {"note"}          # 柜物理组锁死
    assert F[S.DEPARTED] == {"bl_no", "eta", "note"}   # 提单/预计到港/备注可补
    assert F[S.CANCELLED] == frozenset()
    # 全状态覆盖(单一源头完备性)。
    assert set(F.keys()) == set(ShipmentOrderStatus.ALL)


def test_shipment_status_all_covers_matrix():
    assert set(ShipmentOrderStatus.ALL) == set(SHIPMENT_ORDER_TRANSITIONS.keys())


def test_derive_receivable_status_boundaries():
    """0 金额应收(SO 行 unit_price=0 合法)余额 0 = 已收清,不是永远「未收」。"""
    assert derive_receivable_status(0, 0) == ReceivableStatus.PAID
    assert derive_receivable_status(Decimal("5.00"), 0) == ReceivableStatus.UNPAID
    assert derive_receivable_status(Decimal("5.00"), Decimal("2.50")) == \
        ReceivableStatus.PARTIALLY_PAID
    assert derive_receivable_status(Decimal("5.00"), Decimal("5.00")) == ReceivableStatus.PAID
