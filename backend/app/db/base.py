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
    """逻辑删:deleted_at 非空即已删。读默认过滤 deleted_at IS NULL。

    注意 deleted_at 是**功能状态**(读路径每次都要 filter,必须在行上),不是"谁删的"
    归属——归属见下方审计约定,二者不是一套。
    """
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


# ── 审计归属约定(单一源头,别在各模型各写一份)─────────────────────────────
# created_at / updated_at:时间戳标配,业务表经上面 mixin 普遍都有。
# created_by / updated_by / deleted_by(人员归属)默认**不进业务表**:主数据
#   (category / unit / spu / sku / customer / 规格模板…)的"谁创建/更新/删除"统一走
#   audit_logs(resource_type + resource_id + action + user_id;各写服务已 write_audit)。
# 例外 = 当"人"是一等业务字段(要页面展示 / 筛"我的" / 归属统计)才把它上到行上:
#   **本履约后端 quotation_orders(交易归属)与 spus/skus(商品运营录入归属)把 created_by
#   作为业务字段**(展示/筛我的/按人统计直接用;均不加 updated_by/deleted_by)。这是本仓
#   当前事实,不是跨仓铁律——大仓 buildreach 另有 product/rfq/zone 等按需带 created_by 的表,
#   勿据此推断全局。
# 何时给某表补:展示"创建人"→ created_by;筛"我的/我负责的"→ created_by 或 owner_id;
#   展示"最后编辑人"→ updated_by;要完整变更史→ 靠 audit,不靠会被覆盖的 updated_by。
# 主要代价:audit_logs.resource_id 是字符串非 FK,"谁建的这个 SPU"没有行字段直取,
#   只适合低频取证;若运营开始高频问,再给该表加 created_by,别硬从 audit 捞。


# pg_trgm:SKU search_text GIN 索引依赖此扩展。
# create_all(测试)与 alembic(生产)两条建表路径都要保证扩展就绪。
# before_create 在任何 CREATE TABLE 前触发,幂等。
event.listen(
    Base.metadata,
    "before_create",
    DDL("CREATE EXTENSION IF NOT EXISTS pg_trgm"),
)
