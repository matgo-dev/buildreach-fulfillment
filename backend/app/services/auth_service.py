"""认证 service:登录、刷新、改密、登出。M0 基座无自助注册(无 buyer/supplier)。"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.config import settings
from app.core.exceptions import (
    AccountDisabledError,
    AccountLockedError,
    InvalidCredentialsError,
    NotAuthenticatedError,
    NotFoundError,
    TooManyAttemptsError,
    ValidationFailedError,
)
from app.core.request_ip import get_client_ip
from app.core.security import (
    PASSWORD_RULE_MESSAGE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.db.models.audit_log import AuditStatus
from app.db.models.user import User, UserStatus
from app.services.rate_limit import login_rate_limiter

logger = logging.getLogger(__name__)


def _client_ip(request: Request | None) -> str:
    return get_client_ip(request)


def _classify_identifier(identifier: str) -> str:
    """返回 'email' / 'username',用于分支查询。

    M0 无国别手机号解析(见 app/core/phone.py 缺失),不做 phone 归一化识别;
    非邮箱一律按用户名查。
    """
    return "email" if "@" in identifier.strip() else "username"


async def _find_user_by_identifier(db: AsyncSession, identifier: str) -> User | None:
    """二选一识别:邮箱(含 @) / 用户名。

    只查 ACTIVE 用户:DISABLED/DEACTIVATED 账号不允许登录,
    且同一邮箱可能同时存在 ACTIVE + 非活跃记录导致 MultipleResultsFound。
    """
    ident = identifier.strip()
    active_filter = User.status == UserStatus.ACTIVE
    if _classify_identifier(ident) == "email":
        row = await db.execute(select(User).where(User.email == ident, active_filter))
    else:
        row = await db.execute(select(User).where(User.username == ident, active_filter))
    return row.scalar_one_or_none()


def _is_account_locked(user: User) -> bool:
    """账号级锁定未过期?locked_until 为 TIMESTAMPTZ,统一用 aware UTC 比较。"""
    return user.locked_until is not None and user.locked_until > datetime.now(timezone.utc)


async def _is_deactivated_by_identifier(db: AsyncSession, identifier: str) -> bool:
    """identifier 对应的账号是否已注销(DEACTIVATED)。

    仅在 ACTIVE 查询无结果时调用;结果**只进审计**(登录响应统一泛化,防枚举)。
    """
    ident = identifier.strip()
    deactivated_filter = User.status == UserStatus.DEACTIVATED
    if _classify_identifier(ident) == "email":
        row = await db.execute(select(User.id).where(User.email == ident, deactivated_filter))
    else:
        row = await db.execute(select(User.id).where(User.username == ident, deactivated_filter))
    return row.scalar_one_or_none() is not None


async def login(
    db: AsyncSession,
    *,
    identifier: str,
    password: str,
    request: Request | None = None,
) -> dict:
    """identifier 支持邮箱 / 用户名。限流以 identifier+ip 为 key。"""
    ip = _client_ip(request)
    rate_key = identifier.strip().lower()

    if login_rate_limiter.is_locked(rate_key, ip):
        await write_audit(
            db,
            resource_type=AuditResourceType.AUTH,
            action=AuditAction.LOGIN_LOCKED,
            status=AuditStatus.FAILED,
            user_email=identifier,
            request=request,
            error_message="locked",
            extra={"identifier": identifier},
        )
        raise TooManyAttemptsError()

    user = await _find_user_by_identifier(db, identifier)

    # 账号级锁定:在密码校验之前判;锁定期间的尝试不递增计数。
    # 锁定提示暴露「账号存在」—— 公网下锁定可用性(用户须知道为何登不上、找管理员解锁)
    # 与防枚举的权衡,取前者。
    if user is not None and _is_account_locked(user):
        await write_audit(
            db,
            resource_type=AuditResourceType.AUTH,
            action=AuditAction.LOGIN_LOCKED,
            status=AuditStatus.FAILED,
            user_id=user.id,
            user_email=user.email,
            request=request,
            error_message="account locked",
            extra={"identifier": identifier},
        )
        raise AccountLockedError()

    # 用户不存在 / 密码错误 / 已注销 → 统一返回同一个 401,防枚举;
    # 真实原因只进审计(error_message)。
    # 注意:_find_user_by_identifier 只返回 ACTIVE 用户,DISABLED/DEACTIVATED 会走此分支
    if user is None or not verify_password(password, user.password_hash):
        error_detail = "invalid credentials"
        if user is None and await _is_deactivated_by_identifier(db, identifier):
            error_detail = "account deactivated"

        mem_locked_now = login_rate_limiter.record_failure(rate_key, ip)

        # 账号级失败计数(仅命中真实 ACTIVE 用户时):达到阈值 → 锁定 + 计数清零。
        # SQL 原子自增(SET n = n + 1 RETURNING),并发失败登录不丢计数——匹配该列
        # 「落库最强层」的定位,不依赖 ORM 读改写。
        account_locked_now = False
        if user is not None:
            new_count = (await db.execute(
                update(User)
                .where(User.id == user.id)
                .values(failed_login_attempts=User.failed_login_attempts + 1)
                .returning(User.failed_login_attempts)
            )).scalar_one()
            if new_count >= settings.ACCOUNT_LOCK_THRESHOLD:
                user.locked_until = datetime.now(timezone.utc) + timedelta(
                    minutes=settings.ACCOUNT_LOCK_MINUTES
                )
                user.failed_login_attempts = 0
                account_locked_now = True

        action = (
            AuditAction.LOGIN_LOCKED
            if (mem_locked_now or account_locked_now)
            else AuditAction.LOGIN_FAILED
        )
        # write_audit 默认 commit=True,同时把计数/锁定落库
        await write_audit(
            db,
            resource_type=AuditResourceType.AUTH,
            action=action,
            status=AuditStatus.FAILED,
            user_email=user.email if user else identifier,
            user_id=user.id if user else None,
            request=request,
            error_message=error_detail,
            extra={"identifier": identifier},
        )
        if account_locked_now:
            raise AccountLockedError()
        if mem_locked_now:
            raise TooManyAttemptsError()
        raise InvalidCredentialsError()

    # 此处 user 一定是 ACTIVE(_find_user_by_identifier 保证),
    # 保留 DISABLED 检查作为防御性兜底(理论上不会触发)
    if user.status == UserStatus.DISABLED:
        await write_audit(
            db,
            resource_type=AuditResourceType.AUTH,
            action=AuditAction.LOGIN_FAILED,
            status=AuditStatus.FAILED,
            user_id=user.id,
            user_email=user.email,
            request=request,
            error_message="account disabled",
        )
        raise AccountDisabledError()

    # 成功:双道限流一并复位(计数清零 + 解锁,随 LOGIN_SUCCESS 审计一起落库)
    login_rate_limiter.reset(rate_key, ip)
    user.failed_login_attempts = 0
    user.locked_until = None
    access_token, expires_in = create_access_token(user.id, user.email, user.token_version)
    refresh_token = create_refresh_token(user.id, user.email, user.token_version)
    await write_audit(
        db,
        resource_type=AuditResourceType.AUTH,
        action=AuditAction.LOGIN_SUCCESS,
        user_id=user.id,
        user_email=user.email,
        request=request,
        extra={"identifier_used": _classify_identifier(identifier)},
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
    }


async def refresh(
    db: AsyncSession,
    *,
    refresh_token: str | None,
) -> dict:
    """用 refresh token 换新 access token,并轮换 refresh token(滑动 7 天)。

    吊销由 users.token_version 单一源头管辖(改密/管理员重置即 +1,旧 refresh 一并失效),
    不建 jti 黑名单 —— 内部平台威胁模型下重放检测属过度设计。
    must_change_password 用户允许 refresh:强制改密拦截由 guard 层(40007)负责,
    不该把「必须改密」降级成「会话失效」。
    """
    if not refresh_token:
        raise NotAuthenticatedError("Missing refresh token")
    try:
        payload = decode_token(refresh_token, expected_type="refresh")
    except JWTError:
        raise NotAuthenticatedError("Invalid refresh token")

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise NotAuthenticatedError("Invalid token payload")

    user = await db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise NotAuthenticatedError("User not active")
    if int(payload.get("tv", -1)) != user.token_version:
        raise NotAuthenticatedError("Token revoked")

    access_token, expires_in = create_access_token(user.id, user.email, user.token_version)
    new_refresh_token = create_refresh_token(user.id, user.email, user.token_version)
    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
    }


async def change_password(
    db: AsyncSession,
    *,
    user_id: int,
    old_password: str,
    new_password: str,
    request: Request | None = None,
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    if not verify_password(old_password, user.password_hash):
        await write_audit(
            db,
            resource_type=AuditResourceType.AUTH,
            action=AuditAction.PASSWORD_CHANGE,
            status=AuditStatus.FAILED,
            user_id=user.id,
            user_email=user.email,
            request=request,
            error_message="old password incorrect",
        )
        raise InvalidCredentialsError("旧密码错误")
    if not validate_password_strength(new_password):
        raise ValidationFailedError(PASSWORD_RULE_MESSAGE)

    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    # 吊销旧 token，随后签发新 token（改密后自动续登，无需重新输入凭证）
    user.token_version += 1

    await write_audit(
        db,
        resource_type=AuditResourceType.AUTH,
        action=AuditAction.PASSWORD_CHANGE,
        user_id=user.id,
        user_email=user.email,
        request=request,
        commit=False,
    )
    await db.commit()

    # 基于新 token_version 签发，当前会话无缝续登
    access_token, expires_in = create_access_token(user.id, user.email, user.token_version)
    refresh_token = create_refresh_token(user.id, user.email, user.token_version)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
    }


async def logout(
    db: AsyncSession,
    *,
    user_id: int,
    user_email: str,
    request: Request | None = None,
) -> None:
    """无状态 JWT 登出:仅写审计,前端自行清 token。"""
    await write_audit(
        db,
        resource_type=AuditResourceType.AUTH,
        action=AuditAction.LOGOUT,
        user_id=user_id,
        user_email=user_email,
        request=request,
    )
