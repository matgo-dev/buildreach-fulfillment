"""通用响应包装。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

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
