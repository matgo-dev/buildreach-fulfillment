"""客户 schemas。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.languages import is_supported_quote_language


def _require_zh(v: dict) -> dict:
    """name_i18n 校验:zh 必填非空,禁止空串(未填语言不放 key)。"""
    if not isinstance(v, dict) or not v.get("zh"):
        raise ValueError("name_i18n.zh 必填且非空")
    if any(val in ("", None) for val in v.values()):
        raise ValueError("禁止空串/空值(未填语言不放 key)")
    return v


def _valid_quote_language(v: str | None) -> str | None:
    """报价语言:None 或受支持的三选一(单一源头 core.languages)。"""
    if v is not None and not is_supported_quote_language(v):
        raise ValueError("quote_language 必须是 zh/en/sw 之一")
    return v


class CustomerCreateIn(BaseModel):
    name_i18n: dict = Field(...)
    quote_language: str | None = None
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=255)
    address: str | None = None

    _v_name = field_validator("name_i18n")(_require_zh)
    _v_lang = field_validator("quote_language")(_valid_quote_language)


class CustomerOut(BaseModel):
    id: int
    code: str
    name_i18n: dict
    quote_language: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    address: str | None
    status: str
