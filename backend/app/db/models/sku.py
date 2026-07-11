from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin, SoftDeleteMixin


class SkuStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Sku(Base, TimestampUpdateMixin, SoftDeleteMixin):
    __tablename__ = "skus"
    __table_args__ = (
        # pg_trgm GIN 加速 search_text ILIKE 模糊匹配(扩展由 base.py before_create 建)
        Index("ix_skus_search_text_trgm", "search_text",
              postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"}),
        # 内部采购参考价非负兜底
        CheckConstraint("reference_price IS NULL OR reference_price >= 0",
                        name="ck_skus_ref_price_nn"),
        # 状态 DB 兜底(纵深防御,与 category_spec_attributes 的 value_type/source CHECK 同纪律)
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_skus_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # ON DELETE RESTRICT 显式:SPU 被 SKU 引用时不可硬删(同 sku.unit 口径;spus 实际只软删)
    spu_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("spus.id", ondelete="RESTRICT"), nullable=False, index=True)
    sku_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    # FK units.code(两侧显式同 String(20)),ON DELETE RESTRICT(在用单位删不掉);
    # index=True → SQLAlchemy 默认命名 ix_skus_unit(RESTRICT 删检查 + 按单位筛选吃索引)。
    unit: Mapped[str] = mapped_column(
        String(20), ForeignKey("units.code", ondelete="RESTRICT"), nullable=False, index=True)
    reference_price: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    spec_jsonb: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SkuStatus.ACTIVE)
    image: Mapped[str | None] = mapped_column(String(255), nullable=True)
