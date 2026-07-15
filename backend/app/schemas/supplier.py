"""供应商 schemas(照 customers 档次:最小主数据 + 默认采购币种 + 启停)。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _valid_currency(v: str | None) -> str | None:
    if v is not None and not (len(v) == 3 and v.isalpha() and v.isupper()):
        raise ValueError("default_currency 必须是 ISO4217 三字母大写 code(如 USD)")
    return v


class SupplierCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    default_currency: str | None = None
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=255)
    address: str | None = None

    _v_currency = field_validator("default_currency")(_valid_currency)


class SupplierUpdateIn(SupplierCreateIn):
    """编辑:同建单字段(不含 code/status,后者走 activate/deactivate)。"""


class SupplierOut(BaseModel):
    id: int
    code: str
    name: str
    default_currency: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    address: str | None
    status: str


class SupplierListItem(BaseModel):
    id: int
    code: str
    name: str
    default_currency: str | None
    contact_name: str | None
    status: str
    updated_at: datetime
