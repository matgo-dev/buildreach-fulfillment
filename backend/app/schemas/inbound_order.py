"""入库单 schemas。

🔴红线由设计消除:入库单/行**无任何成本字段**(契约 D3),故读投影无需脱敏工厂。
详情内嵌的 PO 摘要走既有 PurchaseOrderOut.build(can_see_cost=...) 脱敏;
payable 块仅在持 payable:read 时由端点组装(整块门控,非字段级)。
"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

# ---------- 写入(建单 / 整单保存)----------


class InboundOrderLineIn(BaseModel):
    """入库行:引用 PO 行 + 本次入库数量。无成本字段(平移快照在 service 从 PO 行取)。"""
    purchase_order_line_id: int
    qty: float = Field(gt=0)
    remark: str | None = None
    sort_order: int = Field(default=0, ge=0)


class InboundOrderCreateIn(BaseModel):
    """基于 CONFIRMED PO 建一张在途入库单。lines 空 → service 抛 41707。"""
    purchase_order_id: int
    carrier_name: str | None = None
    tracking_no: str | None = None
    shipped_at: date | None = None
    eta: date | None = None
    remark: str | None = None
    lines: list[InboundOrderLineIn] = Field(default_factory=list)


class InboundOrderUpdateIn(BaseModel):
    """整单保存(PUT):仅 IN_TRANSIT;必带乐观锁基线(对齐 PO)。PO 归属不可改(单据身份)。行整表重写。"""
    carrier_name: str | None = None
    tracking_no: str | None = None
    shipped_at: date | None = None
    eta: date | None = None
    remark: str | None = None
    lines: list[InboundOrderLineIn] = Field(default_factory=list)
    expected_updated_at: datetime


class InboundOrderReceiveIn(BaseModel):
    """确认入库:实际到货日(默认当天,service 填)。"""
    arrived_at: date | None = None


class InboundOrderUnreceiveIn(BaseModel):
    """撤销入库:留痕原因(可空)。"""
    void_reason: str | None = None


# ---------- 读投影(无成本字段)----------


class InboundOrderLineOut(BaseModel):
    id: int
    inbound_order_id: int
    purchase_order_line_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    language: str
    qty: float
    sort_order: int
    remark: str | None

    @classmethod
    def build(cls, line) -> dict:
        return cls.model_validate(line, from_attributes=True).model_dump()


class InboundOrderOut(BaseModel):
    id: int
    no: str
    purchase_order_id: int
    status: str
    carrier_name: str | None
    tracking_no: str | None
    shipped_at: date | None
    eta: date | None
    arrived_at: date | None
    remark: str | None
    updated_at: datetime

    @classmethod
    def build(cls, order, extra: dict | None = None) -> dict:
        d = cls.model_validate(order, from_attributes=True).model_dump()
        if extra:
            d.update(extra)
        return d


class InboundOrderListItem(BaseModel):
    id: int
    no: str
    purchase_order_id: int
    purchase_order_no: str
    supplier_display: str
    status: str
    carrier_name: str | None
    tracking_no: str | None
    eta: date | None
    arrived_at: date | None
    line_count: int
    total_qty: float
    created_at: datetime


class ReceivableLineOut(BaseModel):
    """PO 可收行(建单器数据源)。无成本字段。"""
    purchase_order_line_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    language: str
    ordered_qty: float
    in_transit_qty: float
    received_qty: float
    remaining_qty: float


class RelatedInboundOrderItem(BaseModel):
    """PO 详情「入库记录区」项(含 CANCELLED 并标状态,可追溯)。无成本字段。"""
    id: int
    no: str
    status: str
    carrier_name: str | None
    tracking_no: str | None
    eta: date | None
    arrived_at: date | None
    created_at: datetime
