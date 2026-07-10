from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SkuStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Sku(Base, TimestampUpdateMixin):
    __tablename__ = "skus"
    __table_args__ = (
        # pg_trgm GIN 加速 search_text ILIKE 模糊匹配(扩展由 base.py before_create 建)
        Index("ix_skus_search_text_trgm", "search_text",
              postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"}),
        # 内部采购参考价非负兜底
        CheckConstraint("reference_price IS NULL OR reference_price >= 0",
                        name="ck_skus_ref_price_nn"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spu_id: Mapped[int] = mapped_column(Integer, ForeignKey("spus.id"), nullable=False, index=True)
    sku_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    reference_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    spec_jsonb: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SkuStatus.ACTIVE)
