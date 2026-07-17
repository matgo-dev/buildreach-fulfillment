"""客户 schemas。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.languages import is_supported_quote_language


def _valid_quote_language(v: str | None) -> str | None:
    """报价语言:None 或受支持的三选一(单一源头 core.languages)。"""
    if v is not None and not is_supported_quote_language(v):
        raise ValueError("quote_language 必须是 zh/en/sw 之一")
    return v


class CustomerCreateIn(BaseModel):
    # 客户名=身份专有名词,单值(非 i18n map);非空、上限对齐 DB String(200)。
    name: str = Field(..., min_length=1, max_length=200)
    quote_language: str | None = None
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=255)
    address: str | None = None

    _v_lang = field_validator("quote_language")(_valid_quote_language)


class CustomerOut(BaseModel):
    id: int
    code: str
    name: str
    quote_language: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    address: str | None
    status: str


class CustomerUpdateIn(CustomerCreateIn):
    """编辑:同建单字段(不含 code/status;code=身份键不可改,status 走 activate/deactivate)。"""


class CustomerListItem(BaseModel):
    id: int
    code: str
    name: str
    quote_language: str | None
    contact_name: str | None
    contact_phone: str | None
    status: str
    updated_at: datetime
