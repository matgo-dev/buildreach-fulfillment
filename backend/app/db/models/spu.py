from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin, SoftDeleteMixin


class SpuStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Spu(Base, TimestampUpdateMixin, SoftDeleteMixin):
    __tablename__ = "spus"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    spu_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    category_code: Mapped[str] = mapped_column(
        String(50), ForeignKey("categories.code"), nullable=False, index=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SpuStatus.ACTIVE)
