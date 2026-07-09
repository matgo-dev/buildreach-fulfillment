from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SuggestionSource:
    SEED = "种子"
    OPERATOR = "运营手加"


class CategorySpecSuggestion(Base, TimestampUpdateMixin):
    """分类规格建议模板(软建议)——属性 label/类型/单位/排序的权威。

    一分类一行,suggestions 为建议项数组。SKU 的 spec_jsonb 不重复存这些。
    """
    __tablename__ = "category_spec_suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("categories.code"), unique=True, nullable=False, index=True
    )
    suggestions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
