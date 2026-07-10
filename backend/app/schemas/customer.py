"""客户 schemas。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _require_zh(v: dict) -> dict:
    """name_i18n 校验:zh 必填非空,禁止空串(未填语言不放 key)。"""
    if not isinstance(v, dict) or not v.get("zh"):
        raise ValueError("name_i18n.zh 必填且非空")
    if any(val == "" for val in v.values()):
        raise ValueError("禁止空串(未填语言不放 key)")
    return v


class CustomerCreateIn(BaseModel):
    name_i18n: dict = Field(...)
    preferred_language: str | None = Field(default=None, max_length=35)
    contact_name: str | None = Field(default=None, max_length=100)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: str | None = Field(default=None, max_length=255)
    address: str | None = None

    _v_name = field_validator("name_i18n")(_require_zh)


class CustomerOut(BaseModel):
    id: int
    code: str
    name_i18n: dict
    preferred_language: str | None
    contact_name: str | None
    contact_phone: str | None
    contact_email: str | None
    address: str | None
    status: str
