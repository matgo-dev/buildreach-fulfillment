"""认证 service:登录、刷新、改密、登出。M0 基座无自助注册(无 buyer/supplier)。"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError
from sqlalchemy import delete, select, update
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
    hash_jti,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.db.models.audit_log import AuditStatus
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User, UserStatus
from app.services.rate_limit import login_rate_limiter

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _issue_refresh_in_family(
    db: AsyncSession, user: User, family_id: str
) -> tuple[str, str]:
    """签发一枚 refresh token 并在指定家族记一行账。返回 (token 明文, jti_hash)。

    row 尚未 flush;调用方在同事务里 flush/commit。issued_at = 记账时刻。
    """
    now = _utcnow()
    token, jti = create_refresh_token(user.id, user.email, user.token_version)
    jti_hash = hash_jti(jti)
    db.add(RefreshToken(
        user_id=user.id,
        family_id=family_id,
        jti_hash=jti_hash,
        issued_at=now,
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    return token, jti_hash


async def _revoke_family(db: AsyncSession, family_id: str) -> None:
    """撤销整个 token 家族(登出 / 重放检测)。set-based,一族有界几行,不逐行。"""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )


def _client_ip(request: Request | None) -> str:
    return get_client_ip(request)


def _classify_identifier(identifier: str) -> str:
    """返回 'email' / 'username',用于分支查询。

    M0 无国别手机号解析(见 app/core/phone.py 缺失),不做 phone 归一化识别;
    非邮箱一律按用户名查。
    """
    return "email" if "@" in identifier.strip() else "username"


async def _find_user_by_identifier(db: AsyncSession, identifier: str, *,
                                   for_update: bool = False) -> User | None:
    """二选一识别:邮箱(含 @) / 用户名。

    只查 ACTIVE 用户:DISABLED/DEACTIVATED 账号不允许登录,
    且同一邮箱可能同时存在 ACTIVE + 非活跃记录导致 MultipleResultsFound。

    for_update=True 时对命中行加悲观锁(SELECT ... FOR UPDATE),把同账号登录的
    「查锁定态 → 验密码 → 递增/锁定」串行化到事务提交,堵住并发失败请求绕过锁检查
    污染计数、漏判 429 的 TOCTOU 窗口。
    """
    ident = identifier.strip()
    active_filter = User.status == UserStatus.ACTIVE
    if _classify_identifier(ident) == "email":
        stmt = select(User).where(User.email == ident, active_filter)
    else:
        stmt = select(User).where(User.username == ident, active_filter)
    if for_update:
        stmt = stmt.with_for_update()
    row = await db.execute(stmt)
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

    # 悲观行锁:同账号并发登录串行化,锁持到本请求事务提交(见 helper docstring)。
    user = await _find_user_by_identifier(db, identifier, for_update=True)

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
        # user 由 FOR UPDATE 持锁读入,同账号请求已串行化,ORM 读改写即安全;
        # 并发的下一次失败请求会阻塞到本次提交,拿锁后读到 locked_until 已设、
        # 在锁检查处直接 429 返回,不会走到这里污染计数。
        account_locked_now = False
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.ACCOUNT_LOCK_THRESHOLD:
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
    # 惰性清理:过期账本行在登录这条低频路径顺手删(set-based 全表谓词,走 expires_at 索引,
    # 任一登录清所有人的过期行)。used/revoked 行 7 天后同样落入此谓词,一个谓词覆盖所有归宿;
    # 父行必先于子行过期(先签发先到期),同批删不触发自引用 SET NULL。无调度基建,不上定时任务。
    await db.execute(delete(RefreshToken).where(RefreshToken.expires_at <= _utcnow()))
    # 新登录开一个 token 家族;row 随下方 LOGIN_SUCCESS 审计一并落库(commit=True)。
    refresh_token, _ = await _issue_refresh_in_family(db, user, uuid.uuid4().hex)
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

    两层吊销:users.token_version = 改密/封号的全局总闸;refresh_tokens 家族账本 =
    单会话精确掐断(轮换作废 + 重放检测)。公网部署威胁模型下二者都必要。
    轮换:查 jti 账本行 → 标父 used、同族派生子;已 used 的父在宽限窗外再现 = 重放 → 撤整族。
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

    jti = payload.get("jti")
    if not jti:
        raise NotAuthenticatedError("Invalid refresh token")

    now = _utcnow()
    # 行锁串行化同一 token 的并发轮换,把「判 used → 决定容忍/撤族 → 派生」原子化。
    row = (await db.execute(
        select(RefreshToken)
        .where(RefreshToken.jti_hash == hash_jti(jti))
        .with_for_update()
    )).scalar_one_or_none()

    if row is None:
        # 签名合法但账本无此行:伪造 / 已惰性清理的过期 token。
        raise NotAuthenticatedError("Unknown refresh token")
    if row.revoked_at is not None:
        raise NotAuthenticatedError("Session revoked")
    if row.expires_at <= now:
        raise NotAuthenticatedError("Refresh token expired")

    first_use = row.used_at is None
    if not first_use:
        # 父 token 已被轮换过 —— 潜在重放。
        grace = timedelta(seconds=settings.REFRESH_REPLAY_GRACE_SECONDS)
        if now - row.used_at > grace:
            # 宽限窗外重现 = 重放 → 撤整族(先记账再抛)。
            await _revoke_family(db, row.family_id)
            await write_audit(
                db,
                resource_type=AuditResourceType.AUTH,
                action=AuditAction.REFRESH_REPLAY,
                status=AuditStatus.FAILED,
                user_id=user.id,
                user_email=user.email,
                error_message="refresh token replay",
                extra={"family_id": row.family_id},
            )
            raise NotAuthenticatedError("Refresh token replay detected")
        # 窗内并发轮换(多标签页竞态):容忍、发新、不动 used_at(防无限撑窗)、不撤族。

    access_token, expires_in = create_access_token(user.id, user.email, user.token_version)
    # 先 flush 子行,父行的自引用 replaced_by_jti_hash 才有可指向的目标。
    new_refresh_token, new_hash = await _issue_refresh_in_family(db, user, row.family_id)
    await db.flush()
    if first_use:
        # used_at 与 replaced_by 成对写(DB 有配对 CHECK 兜底)。
        row.used_at = now
        row.replaced_by_jti_hash = new_hash
    await db.commit()
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

    # 基于新 token_version 签发,当前会话无缝续登。tv 已 +1 使旧族全部作废,
    # 这里开一个新族记账(与 tv 呼应),否则新 refresh token 无账本行、下次轮换会 401。
    access_token, expires_in = create_access_token(user.id, user.email, user.token_version)
    refresh_token, _ = await _issue_refresh_in_family(db, user, uuid.uuid4().hex)
    await db.commit()
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer",
        "expires_in": expires_in,
    }


async def logout(
    db: AsyncSession,
    *,
    refresh_token: str | None,
    user_id: int | None = None,
    user_email: str | None = None,
    request: Request | None = None,
) -> None:
    """登出:撤销 refresh cookie 所属的 token 家族(服务端吊销,非仅清浏览器 cookie)+ 写审计。

    幂等:token 缺失/失效/账本无行都静默跳过撤族;仅在拿到有效用户身份时写 LOGOUT 审计。
    """
    if refresh_token:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except JWTError:
            payload = None
        jti = payload.get("jti") if payload else None
        if jti:
            row = (await db.execute(
                select(RefreshToken).where(RefreshToken.jti_hash == hash_jti(jti))
            )).scalar_one_or_none()
            if row is not None:
                await _revoke_family(db, row.family_id)

    if user_id is not None:
        await write_audit(
            db,
            resource_type=AuditResourceType.AUTH,
            action=AuditAction.LOGOUT,
            user_id=user_id,
            user_email=user_email,
            request=request,
            commit=False,
        )
    await db.commit()
