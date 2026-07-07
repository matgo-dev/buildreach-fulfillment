"""Trace ID 上下文(全链路日志关联)。"""
from __future__ import annotations

from contextvars import ContextVar

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="-")


def get_trace_id() -> str:
    return trace_id_var.get()


def set_trace_id(value: str) -> None:
    trace_id_var.set(value)
