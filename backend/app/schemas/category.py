"""分类 schemas。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _valid_name_i18n(v: dict) -> dict:
    zh = (v or {}).get("zh")
    if not isinstance(zh, str) or not zh.strip():
        raise ValueError("name_i18n.zh 必填")
    return {k: val.strip() if isinstance(val, str) else val
            for k, val in v.items() if val is not None}


class CategoryCreateIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    parent_code: str | None = Field(default=None, max_length=50)
    name_i18n: dict = Field(..., min_length=1)
    sort_order: int = Field(default=0, ge=0)

    _v_name = field_validator("name_i18n")(_valid_name_i18n)


class CategoryUpdateIn(BaseModel):
    name_i18n: dict = Field(..., min_length=1)
    sort_order: int = Field(default=0, ge=0)

    _v_name = field_validator("name_i18n")(_valid_name_i18n)


class CategoryOut(BaseModel):
    id: int
    code: str
    parent_code: str | None
    name_i18n: dict
    level: int
    is_leaf: bool
    is_active: bool
    sort_order: int
    updated_at: datetime
