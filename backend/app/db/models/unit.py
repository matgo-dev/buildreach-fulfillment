from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Unit(Base, TimestampUpdateMixin):
    """SKU 售卖单位专表(spec §11 方案3,非通用字典框架;全局表,独立迁移 0006_units)。

    code-as-PK(非 surrogate id):小查表、code 永久不变(同 categories.code 契约),
    直接 code 做 PK 更简、sku.unit 引 PK 天然省一个 id
    (ff-schema-review #9 已记档:有意分歧,非意外)。

    审计:仅 TimestampUpdateMixin,不加 created_by/updated_by —— 主数据创建/更新/删除人
    走 audit_logs(见 base.py「审计归属约定」单一源头)。
    """
    __tablename__ = "units"
    __table_args__ = (
        CheckConstraint("code ~ '^[a-z0-9_]+$'", name="ck_units_code_fmt"),
        CheckConstraint("sort_order >= 0", name="ck_units_sort_nn"),
    )

    code: Mapped[str] = mapped_column(String(20), primary_key=True)
    label_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
