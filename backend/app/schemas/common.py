"""通用响应包装。"""
from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class Response(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None


class ErrorResponse(BaseModel):
    code: int
    message: str
    data: Any | None = None
    trace_id: str | None = Field(default=None)


LANGS = {"zh", "en", "sw"}


def validate_i18n(v: dict) -> dict:
    """i18n 字典:zh 必填(trim 非空);键 ⊆ LANGS;任意值禁空串/禁 null。"""
    if not isinstance(v, dict):
        raise ValueError("i18n 必须是对象")
    if not (v.get("zh") and str(v["zh"]).strip()):
        raise ValueError("zh 必填且禁空串")
    for k, val in v.items():
        if k not in LANGS:
            raise ValueError(f"不支持的语言键: {k}")
        if val is None or str(val).strip() == "":
            raise ValueError(f"语言 {k} 值禁空串/禁 null")
    return v


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class StatusPatchIn(BaseModel):
    status: Literal["ACTIVE", "INACTIVE"]
