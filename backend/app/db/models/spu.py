from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin, SoftDeleteMixin


class SpuStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Spu(Base, TimestampUpdateMixin, SoftDeleteMixin):
    __tablename__ = "spus"
    __table_args__ = (
        # 品类子树前缀过滤(list_spus 里 category_code LIKE '前缀.%')走索引:本库 locale
        # 非 C,btree 默认 opclass 不支持前缀 LIKE 索引扫描,需 text_pattern_ops 专用索引。
        # 模型在此声明 = 迁移创建 = create_all 建表,三者单一源头,不再靠迁移单方面偷偷加。
        Index("ix_spus_category_code_prefix", "category_code",
              postgresql_ops={"category_code": "text_pattern_ops"}),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spu_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    category_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("categories.code"), nullable=False, index=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SpuStatus.ACTIVE)
    main_image: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    images: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
