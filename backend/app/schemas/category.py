"""分类 schemas。"""
from __future__ import annotations

from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator

_CATEGORY_CODE_RE = re.compile(r"^(?!00(?:\.|$))\d{2}(?:\.(?!000)\d{3}){0,2}$")
_CATEGORY_CODE_MESSAGE = "分类编码格式应为 01 / 01.001 / 01.001.003"


def _valid_category_code(v: str) -> str:
    if not isinstance(v, str):
        return v
    v = v.strip()
    if not _CATEGORY_CODE_RE.fullmatch(v):
        raise ValueError(_CATEGORY_CODE_MESSAGE)
    return v


def _valid_category_code_opt(v: str | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str):
        return v
    v = v.strip()
    if not v:
        return None
    return _valid_category_code(v)


def _valid_name_i18n(v: dict) -> dict:
    zh = (v or {}).get("zh")
    if not isinstance(zh, str) or not zh.strip():
        raise ValueError("name_i18n.zh 必填")
    return {k: val.strip() if isinstance(val, str) else val
            for k, val in v.items() if val is not None}


class CategoryCreateIn(BaseModel):
    code: str = Field(..., min_length=2, max_length=10)
    parent_code: str | None = Field(default=None, max_length=10)
    name_i18n: dict = Field(..., min_length=1)
    sort_order: int = Field(default=0, ge=0)

    _v_code = field_validator("code", mode="before")(_valid_category_code)
    _v_parent_code = field_validator("parent_code", mode="before")(_valid_category_code_opt)
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
