"""分类 schemas。"""
from __future__ import annotations

from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator, model_validator

_CATEGORY_CODE_RE = re.compile(r"^(?!00(?:\.|$))\d{2}(?:\.(?!000)\d{3}){0,2}$")
_CATEGORY_CODE_MESSAGE = "分类编码格式应为 01 / 01.001 / 01.001.003"
_SPEC_OPTION_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


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


class CategorySpecOptionIn(BaseModel):
    code: str | None = Field(default=None, max_length=32)
    label_i18n: dict = Field(..., min_length=1)

    @field_validator("code", mode="before")
    @classmethod
    def _valid_code(cls, v):
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        code = v.strip()
        if not code:
            return None
        if not _SPEC_OPTION_CODE_RE.fullmatch(code):
            raise ValueError("enum option code 必须是 1-32 位 ASCII 机器码")
        return code

    _v_label = field_validator("label_i18n")(_valid_name_i18n)


class CategorySpecAttributeIn(BaseModel):
    label_i18n: dict = Field(..., min_length=1)
    value_type: str = Field(default="string", pattern="^(string|number|enum)$")
    options: list[CategorySpecOptionIn] | None = None
    unit: str | None = Field(default=None, max_length=20)
    sort_order: int | None = Field(default=None, ge=0)
    scope: str = Field(default="sku", pattern="^(spu|sku)$")

    _v_label = field_validator("label_i18n")(_valid_name_i18n)

    @model_validator(mode="after")
    def _valid_options_for_type(self):
        if self.value_type == "enum" and not self.options:
            raise ValueError("enum 属性必须提供 options")
        if self.value_type != "enum" and self.options:
            raise ValueError("非 enum 属性不可携带 options")
        return self


class CategorySpecAttributeOut(BaseModel):
    key: str
    label_i18n: dict
    value_type: str
    options: list[dict] | None
    unit: str
    sort_order: int
    source: str
    category_code: str
    scope: str
