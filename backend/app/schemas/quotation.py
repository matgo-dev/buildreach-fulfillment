"""报价单 schemas。整单保存(表头 + 行数组)+ 乐观锁。"""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import LineQty, LineUnitPrice


class QuotationLineIn(BaseModel):
    id: int | None = None              # 已加载行带 id(对账用),新增行留空
    sku_id: int
    unit_price: LineUnitPrice          # 手录报价价,非负,Numeric(18,2) 强校验
    qty: LineQty                       # 数量为正,Numeric(18,3) 强校验
    remark: str | None = None          # 明细备注
    # 快照(name/spec_text/unit)不收客户端值:服务端从 SKU + SPU∪SKU 规格按报价语言权威冻结,
    # 保证冻结快照忠实反映选料。自定义客户面措辞走 remark,不污染快照。
    sort_order: int = Field(default=0, ge=0)


class QuotationSaveIn(BaseModel):
    """新建报价(POST):表头 + 行数组一次提交。"""
    customer_id: int
    currency: str = Field(..., pattern=r"^[A-Z]{3}$")  # ISO4217 三字母大写 code
    salesperson_id: int | None = None                  # 不传默认=当前用户
    valid_until: date | None = None
    summary: str | None = Field(default=None, max_length=180)
    language: str | None = None
    remark: str | None = None
    lines: list[QuotationLineIn] = Field(default_factory=list)


class QuotationUpdateIn(QuotationSaveIn):
    """整单保存(PUT):必带乐观锁基线。"""
    expected_updated_at: datetime


class QuotationVoidIn(BaseModel):
    reason: str | None = None


class QuotationOrderOut(BaseModel):
    id: int
    no: str
    customer_id: int
    salesperson_id: int
    language: str
    currency: str
    valid_until: date | None
    status: str
    total_amount: float
    summary: str | None
    remark: str | None
    updated_at: datetime


class QuotationLineOut(BaseModel):
    id: int
    quotation_order_id: int
    sku_id: int
    name_snapshot: str
    spec_text_snapshot: str
    unit_snapshot: str
    unit_price: float
    qty: float
    line_total: float
    remark: str | None
    language: str
    sort_order: int


class QuotationListItem(BaseModel):
    id: int
    no: str
    summary: str | None
    customer_display: str
    salesperson_display: str
    status: str
    currency: str
    total_amount: float
    valid_until: date | None
    line_count: int
    created_at: datetime
