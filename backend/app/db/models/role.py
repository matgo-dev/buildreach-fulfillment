from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


# TODO(Q23): Role.scope 字段引入,MVP 仅用 GLOBAL,后续支持组织级/项目级角色再扩展
class RoleScope:
    GLOBAL = "GLOBAL"


class RoleCode:
    ADMIN = "ADMIN"
    PRODUCT_OPERATOR = "PRODUCT_OPERATOR"
    SALES = "SALES"
    ALL = (ADMIN, PRODUCT_OPERATOR, SALES)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default=RoleScope.GLOBAL)
    scope_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
