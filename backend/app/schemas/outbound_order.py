"""出库单 schemas。

🔴红线由设计消除:出库单/行**无任何价格/成本/售价字段**(纯仓单,契约 §1.2/§3),
故读投影无需脱敏工厂。展示快照(name/spec/unit)经 join SO 行取(SO 行冻结单一源头,
出库行不复制)。售价侧在应收(receivables,整表 receivable:read 门控),不经出库 API 回显。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

# ---------- 写入(建单 / 整单保存)----------


class OutboundOrderLineIn(BaseModel):
    """出库行:引用 SO 行 + 本次出库数量。sku 由 service 从 SO 行派生(不采信客户端)。无金额字段。"""
    sales_order_line_id: int
    qty: float = Field(gt=0)


class OutboundOrderCreateIn(BaseModel):
    """基于 CONFIRMED SO + OPEN 柜建一张 DRAFT 出库单。lines 至少一行(空 → 422)。"""
    sales_order_id: int
    shipment_id: int
    note: str | None = None
    lines: list[OutboundOrderLineIn] = Field(min_length=1)


class OutboundOrderUpdateIn(BaseModel):
    """整单保存(PUT):仅 DRAFT;必带乐观锁基线(对齐 PO/入库)。SO/柜 归属不可改(单据身份)。行整表重写。"""
    note: str | None = None
    lines: list[OutboundOrderLineIn] = Field(min_length=1)
    expected_updated_at: datetime


class OutboundOrderRevertIn(BaseModel):
    """撤销出库:作废应收留痕原因(可空)。"""
    void_reason: str | None = None


# ---------- 读投影(无金额字段)----------


class OutboundOrderLineOut(BaseModel):
    id: int
    outbound_order_id: int
    sales_order_line_id: int
    sku_id: int
    qty: float
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    language: str


class OutboundOrderOut(BaseModel):
    id: int
    no: str
    sales_order_id: int
    shipment_id: int
    status: str
    issued_at: datetime | None
    note: str | None
    updated_at: datetime
    # 详情投影附带的柜状态(resolve_order_parties 回填);None = 柜缺失(异常)。
    # 供前端「撤销出库」按钮门禁——柜非 OPEN 时禁用(镜像 41910)。default 兜 model_validate(ORM 无此列)。
    shipment_status: str | None = None

    @classmethod
    def build(cls, order, extra: dict | None = None) -> dict:
        d = cls.model_validate(order, from_attributes=True).model_dump()
        if extra:
            d.update(extra)
        return d


class OutboundOrderListItem(BaseModel):
    id: int
    no: str
    sales_order_id: int
    sales_order_no: str
    shipment_id: int
    shipment_no: str
    container_no: str | None
    status: str
    issued_at: datetime | None
    line_count: int
    total_qty: float
    created_at: datetime


class OutboundableLineOut(BaseModel):
    """SO 可发行(建单器数据源)。无成本/售价字段。available = 可发上限。"""
    sales_order_line_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    language: str
    ordered_qty: float
    inbound_qty: float
    outbound_qty: float
    available_qty: float


class RelatedOutboundOrderItem(BaseModel):
    """SO 详情「关联出库单区」项(含 CANCELLED 并标状态,可追溯)。无金额字段。"""
    id: int
    no: str
    status: str
    shipment_id: int
    shipment_no: str
    container_no: str | None
    issued_at: datetime | None
