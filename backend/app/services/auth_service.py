"""认证 service:登录、改密、登出。M0 基座无自助注册(无 buyer/supplier)。"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.logger import write_audit
from app.core.exceptions import (
    AccountDeactivatedError,
    AccountDisabledError,
    InvalidCredentialsError,
    NotFoundError,
    TooManyAttemptsError,
    ValidationFailedError,
)
from app.core.request_ip import get_client_ip
from app.core.security import (
    PASSWORD_RULE_MESSAGE,
    create_access_token,
    create_refresh_token,
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


async def _is_deactivated_by_identifier(db: AsyncSession, identifier: str) -> bool:
    """identifier 对应的账号是否已注销(DEACTIVATED)。

    仅在 ACTIVE 查询无结果时调用,给登录失败路径提供更明确的错误原因。
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

    # 用户不存在 / 密码错误 → 统一返回 401,防枚举
    # 注意:_find_user_by_identifier 只返回 ACTIVE 用户,DISABLED/DEACTIVATED 会走此分支
    if user is None or not verify_password(password, user.password_hash):
        # DEACTIVATED 账号给专属提示(不泄露密码对错,但业务上需要区分)
        if user is None and await _is_deactivated_by_identifier(db, identifier):
            await write_audit(
                db,
                resource_type=AuditResourceType.AUTH,
                action=AuditAction.LOGIN_FAILED,
                status=AuditStatus.FAILED,
                user_email=identifier,
                request=request,
                error_message="account deactivated",
                extra={"identifier": identifier},
            )
            raise AccountDeactivatedError()

        locked_now = login_rate_limiter.record_failure(rate_key, ip)
        action = AuditAction.LOGIN_LOCKED if locked_now else AuditAction.LOGIN_FAILED
        await write_audit(
            db,
            resource_type=AuditResourceType.AUTH,
            action=action,
            status=AuditStatus.FAILED,
            user_email=user.email if user else identifier,
            user_id=user.id if user else None,
            request=request,
            error_message="invalid credentials",
            extra={"identifier": identifier},
        )
        if locked_now:
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

    # 成功
    login_rate_limiter.reset(rate_key, ip)
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
