"""单据行数量/单价受控 Decimal 边界单测(报价/采购/入库/出库写入 schema)。

历史:行价量原为裸 float,静默接受 inf/1e100 → 下游 Decimal(str(...)) 撞 Numeric 溢出成 500。
改用 common.LineQty/LineUnitPrice(对齐 DB Numeric 精度,allow_inf_nan=False),脏输入在 422 层拒。
"""
import pytest
from pydantic import ValidationError

from app.schemas.inbound_order import InboundOrderLineIn
from app.schemas.outbound_order import OutboundOrderLineIn
from app.schemas.purchase_order import PurchaseOrderLineIn
from app.schemas.quotation import QuotationLineIn


def _price_line(cls, price):
    if cls is QuotationLineIn:
        return cls(sku_id=1, unit_price=price, qty=1)
    return cls(source_sales_order_line_id=1, unit_price=price, qty=1)


@pytest.mark.parametrize("cls", [QuotationLineIn, PurchaseOrderLineIn])
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 1e100, -1])
def test_price_rejects_dirty(cls, bad):
    """单价拒 inf/nan/溢出/负数(unit_price ge=0)。"""
    with pytest.raises(ValidationError):
        _price_line(cls, bad)


@pytest.mark.parametrize("cls", [QuotationLineIn, PurchaseOrderLineIn])
def test_price_rejects_over_precision(cls):
    """单价超两位小数被拒(对齐 Numeric(18,2))。"""
    with pytest.raises(ValidationError):
        _price_line(cls, "1.234")


@pytest.mark.parametrize("cls", [QuotationLineIn, PurchaseOrderLineIn])
def test_price_accepts_valid(cls):
    for good in ["7.5", "0.1", "100", "0"]:
        assert _price_line(cls, good).unit_price is not None


def _qty_line(cls, qty):
    if cls is QuotationLineIn:
        return cls(sku_id=1, unit_price=1, qty=qty)
    if cls is PurchaseOrderLineIn:
        return cls(source_sales_order_line_id=1, unit_price=1, qty=qty)
    if cls is InboundOrderLineIn:
        return cls(purchase_order_line_id=1, qty=qty)
    return cls(sales_order_line_id=1, qty=qty)


@pytest.mark.parametrize(
    "cls", [QuotationLineIn, PurchaseOrderLineIn, InboundOrderLineIn, OutboundOrderLineIn])
@pytest.mark.parametrize("bad", [float("inf"), float("nan"), 1e100, 0, -1])
def test_qty_rejects_dirty(cls, bad):
    """数量拒 inf/nan/溢出/非正(qty gt=0)。"""
    with pytest.raises(ValidationError):
        _qty_line(cls, bad)


@pytest.mark.parametrize(
    "cls", [QuotationLineIn, PurchaseOrderLineIn, InboundOrderLineIn, OutboundOrderLineIn])
def test_qty_over_precision_rejected(cls):
    """数量超三位小数被拒(对齐 Numeric(18,3))。"""
    with pytest.raises(ValidationError):
        _qty_line(cls, "1.2345")
