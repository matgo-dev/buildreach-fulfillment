from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class SupplierStatus:
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ALL = (ACTIVE, INACTIVE)


class Supplier(Base, TimestampUpdateMixin):
    __tablename__ = "suppliers"
    __table_args__ = (
        # 状态 DB 兜底(与 customers/skus/spus 的 status CHECK 同纪律)
        CheckConstraint("status IN ('ACTIVE','INACTIVE')", name="ck_suppliers_status"),
        # 采购默认币种存 ISO4217 三字母大写 code;可空(不填=建 PO 时无默认,采购员选)。
        CheckConstraint(
            "default_currency IS NULL OR default_currency ~ '^[A-Z]{3}$'",
            name="ck_suppliers_currency_iso4217"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    # 供应商名=专有名词(身份),非可翻译展示标签,单列存实际名(同 customers,不建 i18n map)。
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 采购默认币种(常≠销售币种);建 PO 带出默认值,采购员可改。
    default_currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=SupplierStatus.ACTIVE)
