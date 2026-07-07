"""密码哈希 + JWT 编解码。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 全局密码规则:6-20 位,仅字母和数字(对齐阿里国际站)。
PASSWORD_MIN_LENGTH = 6
PASSWORD_MAX_LENGTH = 20

# 错误文案前后端逐字一致(frontend/src/lib/validators.ts 同步)
PASSWORD_RULE_MESSAGE = "密码须 6-20 位,仅限字母和数字"


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd_ctx.verify(plain, hashed)
    except Exception:
        return False


def validate_password_strength(plain: str) -> bool:
    """6-20 位,仅字母和数字。"""
    if not (PASSWORD_MIN_LENGTH <= len(plain) <= PASSWORD_MAX_LENGTH):
        return False
    return plain.isalnum() and plain.isascii()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: int, email: str, token_version: int = 0) -> tuple[str, int]:
    expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    exp = _now_utc() + timedelta(seconds=expires_in)
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "access",
        "tv": token_version,
        "iat": int(_now_utc().timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_in


def create_refresh_token(user_id: int, email: str, token_version: int = 0) -> str:
    exp = _now_utc() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "refresh",
        "tv": token_version,
        "iat": int(_now_utc().timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_password_reset_token(user_id: int, email: str) -> str:
    """生成密码重置 JWT，15 分钟有效。"""
    exp = _now_utc() + timedelta(minutes=15)
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "password_reset",
        "iat": int(_now_utc().timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str, expected_type: Literal["access", "refresh", "password_reset"] = "access") -> dict[str, Any]:
    """解码并校验 JWT。失败抛 JWTError(由调用方转 401)。"""
    payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    if payload.get("type") != expected_type:
        raise JWTError("Wrong token type")
    return payload
