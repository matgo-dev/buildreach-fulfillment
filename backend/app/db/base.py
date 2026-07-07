"""SQLAlchemy Declarative Base + 时间字段 mixin。

时间统一 UTC 存储,默认值在应用层赋(`_utcnow()` 返回 naive UTC datetime)。
PG 的 TIMESTAMP WITHOUT TIME ZONE 不接受 tz-aware datetime,所以应用层用 naive 但语义仍 UTC。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """应用层强制 UTC,返回 naive datetime 以兼容 PG 的 TIMESTAMP WITHOUT TIME ZONE。

    语义仍是 UTC — 所有读写约定都 UTC,不带 tz 标识只是为了 DB 字段兼容。
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )


class TimestampUpdateMixin(TimestampMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
