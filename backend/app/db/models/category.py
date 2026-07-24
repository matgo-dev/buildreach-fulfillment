from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class Category(Base, TimestampUpdateMixin):
    """分类树(照搬前台结构 + 数据,只读引用,M1 无管理 UI)。

    code 为业务主键(点分数字 XX.XXX.XXX,永久不变契约,关联引 code 不引 id)。
    """
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("level >= 1", name="ck_categories_level"),
        CheckConstraint("sort_order >= 0", name="ck_categories_sort_nn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # unique=True(不加 index=True):PG UNIQUE 约束自带索引,且必须内联在
    # CREATE TABLE 语句中,自引用 FK(parent_code → categories.code)才能在同一条
    # DDL 里引用到。若额外加 index=True,SQLAlchemy 会把唯一性拆成独立的
    # CREATE UNIQUE INDEX 语句(建表之后才执行),导致 FK 建表时报
    # "no unique constraint matching given keys"。
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    parent_code: Mapped[str | None] = mapped_column(
        String(50), ForeignKey("categories.code", ondelete="RESTRICT"), nullable=True, index=True
    )
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    is_leaf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
