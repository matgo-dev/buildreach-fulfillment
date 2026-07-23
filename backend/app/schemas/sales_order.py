"""销售单 schemas + 红线脱敏构造工厂。转销售(锁档报价→销售单)本增量:只读投影,无写 schema(create 走 convert)。

🔴红线:客户售价(unit_price)/ 行额(line_total)/ 成交额(total_amount)对无 `receivable:read`
者置 null。可见性下沉到 `.build(..., can_see_price=...)` 构造工厂(单点经 redact_fields),
让「新出口忘记脱敏而裸露售价」在结构上更难发生,而非 dump 后再 patch。
SALES / FINANCE 持 receivable:read;PURCHASER / LOGISTICS 不持(浏览 SO 发起采购/出库,不看对客售价)。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.rbac.redaction import SO_LINE_PRICE_FIELDS, SO_PRICE_FIELDS, redact_fields


class SalesOrderCancelIn(BaseModel):
    """整单取消:原因留痕(可空,上限挡误粘贴)。"""
    reason: str | None = Field(default=None, max_length=500)


class SalesOrderOut(BaseModel):
    id: int
    no: str
    source_quotation_id: int
    customer_id: int
    salesperson_id: int
    language: str
    currency: str
    status: str
    total_amount: float | None    # 🔴 无 receivable:read → null
    summary: str | None
    remark: str | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    updated_at: datetime

    @classmethod
    def build(cls, so, extra: dict | None = None, *, can_see_price: bool) -> dict:
        d = cls.model_validate(so, from_attributes=True).model_dump()
        d = redact_fields(d, SO_PRICE_FIELDS, visible=can_see_price)
        if extra:
            d.update(extra)
        return d


class SalesOrderLineOut(BaseModel):
    id: int
    sales_order_id: int
    sku_id: int
    source_quotation_line_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    unit_price: float | None      # 🔴 无 receivable:read → null
    qty: float
    line_total: float | None      # 🔴 无 receivable:read → null
    remark: str | None
    language: str
    sort_order: int

    @classmethod
    def build(cls, line, extra: dict | None = None, *, can_see_price: bool) -> dict:
        d = cls.model_validate(line, from_attributes=True).model_dump()
        d = redact_fields(d, SO_LINE_PRICE_FIELDS, visible=can_see_price)
        if extra:
            d.update(extra)
        return d


class SalesOrderListItem(BaseModel):
    id: int
    no: str
    summary: str | None
    customer_display: str
    salesperson_display: str
    status: str
    currency: str
    total_amount: float | None    # 🔴 无 receivable:read → null
    line_count: int
    created_at: datetime
    # 采购进度(轴2 派生,非红线):NOT_ORDERED/PARTIALLY_ORDERED/FULLY_ORDERED。
    purchase_progress: str | None = None

    @classmethod
    def build(cls, item, *, can_see_price: bool) -> dict:
        d = cls.model_validate(item).model_dump()
        return redact_fields(d, SO_PRICE_FIELDS, visible=can_see_price)
