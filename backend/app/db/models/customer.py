from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class CustomerStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Customer(Base, TimestampUpdateMixin):
    __tablename__ = "customers"
    __table_args__ = (
        # 状态 DB 兜底(纵深防御,与 skus/spus 的 status CHECK 同纪律)
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_customers_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name_i18n: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # 客户报价语言偏好:三选一(zh/en/sw),值域唯一源头 core.languages.SUPPORTED_QUOTE_LANGUAGES,
    # 应用层校验(不在 DB 内联枚举副本);运营录入下拉可选,不填=NULL→建单默认 zh。
    quote_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=CustomerStatus.ACTIVE)
