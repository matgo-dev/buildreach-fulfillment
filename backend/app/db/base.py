"""SQLAlchemy Declarative Base + 时间字段 mixin。

时间统一 UTC 存储,默认值在应用层赋(`_utcnow()` 返回 naive UTC datetime)。
PG 的 TIMESTAMP WITHOUT TIME ZONE 不接受 tz-aware datetime,所以应用层用 naive 但语义仍 UTC。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DDL, DateTime, event
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


class SoftDeleteMixin:
    """逻辑删:deleted_at 非空即已删。读默认过滤 deleted_at IS NULL。"""
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


# pg_trgm:SKU search_text GIN 索引依赖此扩展。
# create_all(测试)与 alembic(生产)两条建表路径都要保证扩展就绪。
# before_create 在任何 CREATE TABLE 前触发,幂等。
event.listen(
    Base.metadata,
    "before_create",
    DDL("CREATE EXTENSION IF NOT EXISTS pg_trgm"),
)
