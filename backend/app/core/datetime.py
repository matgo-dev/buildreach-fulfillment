"""公共 datetime 工具 — 统一 tz 归一逻辑,消灭内联散写。"""
from __future__ import annotations

from datetime import datetime, timezone


def to_naive_utc(dt: datetime | None) -> datetime | None:
    """aware → UTC 去 tzinfo;naive → 视为 UTC 直接返回;None → None。"""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
