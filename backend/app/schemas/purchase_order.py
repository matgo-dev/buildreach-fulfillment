"""采购单 schemas + 红线脱敏构造工厂。

🔴红线:采购价(unit_price)/ 行额(line_total)/ 单头金额(total_amount)对无 `purchase:read_cost`
者置 null。可见性下沉到 `.build(..., can_see_cost=...)` 构造工厂(单点经 redact_fields),
让「新出口忘记脱敏而裸露成本」在结构上更难发生,而非 dump 后 patch。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.rbac.redaction import PO_COST_FIELDS, PO_LINE_COST_FIELDS, redact_fields
from app.schemas.common import LineQty, LineUnitPrice

# ---------- 写入(建单 / 编辑对账)----------


class PurchaseOrderLineIn(BaseModel):
    """建单行(无 id)。"""
    source_sales_order_line_id: int
    qty: LineQty
    unit_price: LineUnitPrice
    remark: str | None = None
    sort_order: int = Field(default=0, ge=0)


class PurchaseOrderCreateIn(BaseModel):
    """基于 SO 建一张 PO(单一供应商)。lines 允许空 → service 抛 41608(非 422)。"""
    source_sales_order_id: int
    supplier_id: int
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    remark: str | None = None
    lines: list[PurchaseOrderLineIn] = Field(default_factory=list)


class PurchaseOrderLineEditIn(BaseModel):
    """编辑行:已存行带 id(对账 UPDATE),新行不带 id(INSERT)。"""
    id: int | None = None
    source_sales_order_line_id: int
    qty: LineQty
    unit_price: LineUnitPrice
    remark: str | None = None
    sort_order: int = Field(default=0, ge=0)


class PurchaseOrderUpdateIn(BaseModel):
    """整单保存(PUT):仅 DRAFT;必带乐观锁基线。source_sales_order_id 不可改(单据身份)。"""
    supplier_id: int
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    remark: str | None = None
    lines: list[PurchaseOrderLineEditIn] = Field(default_factory=list)
    expected_updated_at: datetime


# ---------- 读投影(带红线脱敏工厂)----------


class PurchaseOrderLineOut(BaseModel):
    id: int
    purchase_order_id: int
    sku_id: int
    source_sales_order_line_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    unit_price: float | None      # 🔴 无 read_cost → null
    qty: float
    line_total: float | None      # 🔴 无 read_cost → null
    language: str
    sort_order: int
    remark: str | None

    @classmethod
    def build(cls, line, *, can_see_cost: bool) -> dict:
        d = cls.model_validate(line, from_attributes=True).model_dump()
        return redact_fields(d, PO_LINE_COST_FIELDS, visible=can_see_cost)


class PurchaseOrderOut(BaseModel):
    id: int
    no: str
    source_sales_order_id: int
    supplier_id: int
    currency: str
    status: str
    total_amount: float | None    # 🔴 无 read_cost → null
    remark: str | None
    updated_at: datetime

    @classmethod
    def build(cls, po, extra: dict | None = None, *, can_see_cost: bool) -> dict:
        d = cls.model_validate(po, from_attributes=True).model_dump()
        d = redact_fields(d, PO_COST_FIELDS, visible=can_see_cost)
        if extra:
            d.update(extra)
        return d


class PurchaseOrderListItem(BaseModel):
    id: int
    no: str
    source_sales_order_id: int
    source_sales_order_no: str
    supplier_id: int
    supplier_display: str
    status: str
    currency: str
    total_amount: float | None    # 🔴 无 read_cost → null
    line_count: int
    created_at: datetime

    @classmethod
    def build(cls, item: dict, *, can_see_cost: bool) -> dict:
        d = cls.model_validate(item).model_dump()
        return redact_fields(d, PO_COST_FIELDS, visible=can_see_cost)


class RelatedPurchaseOrderItem(BaseModel):
    """SO 详情「关联采购单区」项(仅 purchase:read 下发)。含 CANCELLED 并标状态(可追溯)。
    金额红线:无 read_cost → null;供应商身份红线由端点级 purchase:read 门控(此结构本就不下发给 SALES)。"""
    id: int
    no: str
    status: str
    supplier_id: int
    supplier_display: str
    currency: str
    total_amount: float | None

    @classmethod
    def build(cls, item: dict, *, can_see_cost: bool) -> dict:
        d = cls.model_validate(item).model_dump()
        return redact_fields(d, PO_COST_FIELDS, visible=can_see_cost)
