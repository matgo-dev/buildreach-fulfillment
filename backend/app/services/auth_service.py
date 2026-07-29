"""认证 service:登录、刷新、改密、登出。M0 基座无自助注册(无 buyer/supplier)。"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, select, update
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
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_jti,
    hash_password_async,
    validate_password_strength,
    verify_password_async,
)
from app.db.models.audit_log import AuditStatus
from app.db.models.refresh_token import RefreshToken
from app.db.models.refresh_token_family import RefreshTokenFamily
from app.db.models.user import User, UserStatus
from app.services.rate_limit import login_rate_limiter

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _open_family(db: AsyncSession, user: User) -> str:
    """开一个新家族(＝一次登录/改密续登的会话),返回 family_id。

    显式 flush 族行:二者无 ORM relationship,UoW 不保证跨类 INSERT 先族后成员,
    须先落族行,后续成员 token 的 FK 才有可指向目标(同事务未提交即可见)。
    """
    family_id = uuid.uuid4().hex
    db.add(RefreshTokenFamily(id=family_id, user_id=user.id, created_at=_utcnow()))
    await db.flush()
    return family_id


async def _issue_refresh_in_family(
    db: AsyncSession, user: User, family_id: str
) -> tuple[str, str]:
    """在已存在的家族里签发一枚 refresh token 并记一行账。返回 (token 明文, jti_hash)。

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
    """撤销整个 token 家族(登出 / 重放检测):在族级承载行写 revoked_at。

    O(1) 单行原子 UPDATE,覆盖该族**所有成员**——含并发 refresh 刚派生、撤族语句快照外的
    新成员(它们的存活统一读 family.revoked_at,不在成员行上判)。与 refresh 派生前的
    `SELECT family FOR UPDATE` 互斥串行,无幻影窗口(错题集 A8)。幂等:重复撤不改时刻。
    """
    await db.execute(
        update(RefreshTokenFamily)
        .where(RefreshTokenFamily.id == family_id,
               RefreshTokenFamily.revoked_at.is_(None))
        .values(revoked_at=_utcnow())
    )


async def _purge_expired(db: AsyncSession) -> None:
    """惰性清理(登录路径触发,set-based 有界):删过期成员行,再删清空后的空族。

    顺序:先删 token(family FK RESTRICT 要求族行不先于成员删),再删无任何成员的族
    (含被撤后成员全过期的死族)。两条谓词走索引/主键,全表但有界(稳态 ≈ 7 天滚动窗签发量)。
    """
    await db.execute(delete(RefreshToken).where(RefreshToken.expires_at <= _utcnow()))
    await db.execute(
        delete(RefreshTokenFamily).where(
            ~exists().where(RefreshToken.family_id == RefreshTokenFamily.id)
        )
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
    # verify_password_async:走线程池(不阻塞事件循环)+ 用户不存在时对 dummy hash 跑一次
    # 等化耗时(堵登录时序枚举,与上方「统一 401」防枚举同一层意图)。
    password_ok = await verify_password_async(
        password, user.password_hash if user is not None else None)
    if user is None or not password_ok:
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
    # 惰性清理:登录这条低频路径顺手删过期成员 + 空族(无调度基建,不上定时任务)。
    await _purge_expired(db)
    # 新登录开一个 token 家族(先落族行,成员 FK 才有目标);随 LOGIN_SUCCESS 审计一并 commit。
    family_id = await _open_family(db, user)
    refresh_token, _ = await _issue_refresh_in_family(db, user, family_id)
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
    except TokenError:
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
    jti_hash = hash_jti(jti)

    now = _utcnow()
    # ① 列级读本 token 所属族 id —— 不实体化成员行,不进 identity map;后续锁下重读才是新值
    #    (错题集 A1「首锁即读」:整行无锁预读会被 identity map 缓存成旧对象)。
    family_id = (await db.execute(
        select(RefreshToken.family_id).where(RefreshToken.jti_hash == jti_hash)
    )).scalar_one_or_none()
    if family_id is None:
        # 签名合法但账本无此行:伪造 / 已惰性清理的过期 token。
        raise NotAuthenticatedError("Unknown refresh token")

    # ② 锁族级承载行(组级锁点):把「撤族」与「派生新成员」串行化 —— 撤族的原子 UPDATE 与本
    #    FOR UPDATE 争同一行写锁,派生只能在撤族前或后发生,并发派生的成员不再逃逸(错题集 A8)。
    family = (await db.execute(
        select(RefreshTokenFamily)
        .where(RefreshTokenFamily.id == family_id)
        .with_for_update()
    )).scalar_one_or_none()
    if family is None or family.revoked_at is not None:
        # 族已撤(登出 / 重放)→ 该族**任何**成员(含撤族后并发派生的)一律失效。
        raise NotAuthenticatedError("Session revoked")

    # ③ 族锁在手,首次实体化成员行即锁下最新态(used_at 反映并发轮换结果,A1)。
    row = (await db.execute(
        select(RefreshToken)
        .where(RefreshToken.jti_hash == jti_hash)
        .with_for_update()
    )).scalar_one_or_none()
    if row is None:
        # 极窄竞态:读到 family_id 后、锁族前本行被惰性清理删除。按未知 token 处理。
        raise NotAuthenticatedError("Unknown refresh token")
    if row.expires_at <= now:
        raise NotAuthenticatedError("Refresh token expired")

    first_use = row.used_at is None
    if not first_use:
        # 父 token 已被轮换过 —— 潜在重放。
        grace = timedelta(seconds=settings.REFRESH_REPLAY_GRACE_SECONDS)
        if now - row.used_at > grace:
            # 宽限窗外重现 = 重放 → 撤整族(族锁在手,直接写族行;先记账再抛)。
            await _revoke_family(db, family_id)
            await write_audit(
                db,
                resource_type=AuditResourceType.AUTH,
                action=AuditAction.REFRESH_REPLAY,
                status=AuditStatus.FAILED,
                user_id=user.id,
                user_email=user.email,
                error_message="refresh token replay",
                extra={"family_id": family_id},
            )
            raise NotAuthenticatedError("Refresh token replay detected")
        # 窗内并发轮换(多标签页竞态):容忍、发新、不动 used_at(防无限撑窗)、不撤族。

    access_token, expires_in = create_access_token(user.id, user.email, user.token_version)
    # 先 flush 子行,父行的自引用 replaced_by_jti_hash 才有可指向的目标。
    new_refresh_token, new_hash = await _issue_refresh_in_family(db, user, family_id)
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
    if not await verify_password_async(old_password, user.password_hash):
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

    user.password_hash = await hash_password_async(new_password)
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

    # 基于新 token_version 签发,当前会话无缝续登。tv 已 +1 使旧族全部作废(全局总闸,
    # 旧族行留待惰性清理),这里开一个新族记账,否则新 refresh token 无账本行、下次轮换会 401。
    access_token, expires_in = create_access_token(user.id, user.email, user.token_version)
    family_id = await _open_family(db, user)
    refresh_token, _ = await _issue_refresh_in_family(db, user, family_id)
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
    """登出:撤销 refresh cookie 所属的 token 家族(服务端吊销 refresh,非仅清浏览器 cookie)+ 写审计。

    注意:只吊销 refresh 家族(续期链断,无法再换新 access)。已签发的 access token 是无状态的,
    在其 ACCESS_TOKEN_EXPIRE_MINUTES(15min)有效期内仍可用——这是无状态 JWT 的固有取舍;需要
    即时全设备断权走改密/重置(token_version+1)。故「登出即刻断权」仅对 refresh 成立。

    幂等:token 缺失/失效/账本无行都静默跳过撤族;仅在拿到有效用户身份时写 LOGOUT 审计。
    """
    family_id: str | None = None
    if refresh_token:
        try:
            payload = decode_token(refresh_token, expected_type="refresh")
        except TokenError:
            payload = None
        jti = payload.get("jti") if payload else None
        if jti:
            # 列级取 family_id(不实体化成员行);撤族 = 族级承载行原子 UPDATE,
            # 与并发 refresh 派生前的 SELECT family FOR UPDATE 争同一行写锁而串行。
            family_id = (await db.execute(
                select(RefreshToken.family_id)
                .where(RefreshToken.jti_hash == hash_jti(jti))
            )).scalar_one_or_none()
            if family_id is not None:
                await _revoke_family(db, family_id)

    if user_id is not None:
        await write_audit(
            db,
            resource_type=AuditResourceType.AUTH,
            action=AuditAction.LOGOUT,
            user_id=user_id,
            user_email=user_email,
            request=request,
            # 定位本次登出撤的是哪个会话(一用户多设备并发多族);None = 未命中账本行。
            extra={"family_id": family_id},
            commit=False,
        )
    await db.commit()
