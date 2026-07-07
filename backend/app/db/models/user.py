from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampUpdateMixin


class UserStatus:
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEACTIVATED = "DEACTIVATED"


class User(Base, TimestampUpdateMixin):
    __tablename__ = "users"
    __table_args__ = (
        # 全状态唯一约束:禁用账号不释放邮箱/用户名/手机号,恢复走启用流程
        Index("uq_users_email", "email", unique=True),
        Index("uq_users_username", "username", unique=True),
        Index("uq_users_phone", "phone", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # 用户名:选填,登录时可作为 email 的替代凭证
    username: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # 手机号:买方主登录凭证(坦桑 +255 E.164),其他角色选填
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    # WhatsApp 号码:买方注册时填写,独立于手机号
    whatsapp: Mapped[str | None] = mapped_column(String(30), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=UserStatus.ACTIVE)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 会话吊销版本号:嵌入 JWT tv claim,改密/强制下线时 +1,使旧 token 一次失效
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # 用户语言偏好(本轮仅 SUPPLIER 自助注册 Step 2 写入,其他场景为 NULL;TODO(T-LANG-CHANGE) 用户自助切换入口)
    language_preference: Mapped[str | None] = mapped_column(String(35), nullable=True)
