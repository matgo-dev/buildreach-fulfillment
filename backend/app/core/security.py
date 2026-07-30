"""密码哈希 + JWT 编解码。"""
from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from jwt import PyJWTError
from passlib.context import CryptContext

from app.core.config import settings

# JWT 签名算法钉死为常量,不走可配置项:本仓只用对称密钥(HS256),没有 RS/ES 的密钥管理
# 路径;做成 env 可配只会平添误配面(如误设 "none")。换算法须改这一处并配套密钥体系。
_JWT_ALG: Literal["HS256"] = "HS256"


class TokenError(Exception):
    """JWT 签发/校验失败的统一出口。

    本模块是全仓唯一直接接触 JWT 库的地方,调用方只认这个异常,不 import 底层库——
    换库时改动收敛在这一个文件。
    """

_pwd_ctx = CryptContext(
    schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.BCRYPT_ROUNDS
)

# 时序等化用的 dummy hash:登录时账号不存在也对它跑一次 verify,消除「跑不跑 bcrypt」的
# 侧信道(否则不存在账号毫秒返回、存在账号 ~0.3s,可无统计单次枚举出有效账号)。
# 同 CryptContext 生成,rounds 自动随 BCRYPT_ROUNDS 对齐(生成一次,进程内复用)。
_DUMMY_PASSWORD_HASH = _pwd_ctx.hash("timing-equalizer-not-a-real-password")

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


async def hash_password_async(plain: str) -> str:
    """bcrypt 哈希走线程池:哈希是 CPU 阻塞(rounds=12 ≈ 0.3s),直接在协程里跑会占死事件
    循环、拖垮全服务并发。异步写入口(注册/改密/重置)一律用本函数。"""
    return await asyncio.to_thread(hash_password, plain)


async def verify_password_async(plain: str, hashed: str | None) -> bool:
    """bcrypt 校验走线程池(同 hash_password_async 的阻塞理由)。

    hashed=None(账号不存在)时对 dummy hash 跑一次校验再恒返 False:等化「存在/不存在」两条
    路径的耗时,堵死登录时序枚举。始终不因 dummy 命中而误判为真。"""
    ok = await asyncio.to_thread(
        verify_password, plain, hashed if hashed is not None else _DUMMY_PASSWORD_HASH)
    return ok if hashed is not None else False


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
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=_JWT_ALG)
    return token, expires_in


def create_refresh_token(user_id: int, email: str, token_version: int = 0) -> tuple[str, str]:
    """签发 refresh token,返回 (token, jti)。

    jti = 本 token 的随机唯一 id,服务端只存其哈希(hash_jti)入 refresh_tokens 账本用于
    轮换作废 / 重放检测;调用方拿 jti 记账。
    """
    jti = uuid.uuid4().hex
    exp = _now_utc() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "type": "refresh",
        "tv": token_version,
        "jti": jti,
        "iat": int(_now_utc().timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=_JWT_ALG)
    return token, jti


def hash_jti(jti: str) -> str:
    """refresh token jti 的 sha256 十六进制。存哈希不存原文:库泄漏 ≠ token 泄漏。

    jti 为高熵 uuid4,无需加盐。
    """
    return hashlib.sha256(jti.encode()).hexdigest()


def decode_token(token: str, expected_type: Literal["access", "refresh"] = "access") -> dict[str, Any]:
    """解码并校验 JWT。失败抛 TokenError(由调用方转 401)。"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[_JWT_ALG],
                             options={"require": ["exp"]})
    except PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise TokenError("Wrong token type")
    return payload
