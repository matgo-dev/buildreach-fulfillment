"""认证路由 /api/v1/auth/*(login/refresh/change-password/logout/me)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import CurrentUser, get_current_user, oauth2_scheme
from app.core.exceptions import BusinessError, success
from app.db.session import get_db
from app.rbac.guards import block_if_must_change_password
from app.schemas.auth import ChangePasswordIn, LoginIn, MeOut, TokenOut
from app.schemas.user import SelfProfileUpdateIn
from app.services import auth_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """统一封装:把 refresh token 写入 httpOnly cookie(SameSite 默认 lax,见 config)。"""
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
        path=settings.REFRESH_COOKIE_PATH,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
    )


def _delete_refresh_cookie_headers() -> dict[str, str]:
    """生成清 refresh cookie 的 Set-Cookie 头(供异常响应携带,经 biz_exc_handler 透传)。"""
    tmp = Response()
    tmp.delete_cookie(key=settings.REFRESH_COOKIE_NAME, path=settings.REFRESH_COOKIE_PATH)
    return {"set-cookie": tmp.headers["set-cookie"]}


@router.post("/login", summary="登录(access 在 body,refresh 在 httpOnly cookie)")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    tokens = await auth_service.login(
        db,
        identifier=body.identifier,
        password=body.password,
        request=request,
    )
    # refresh 不入 body,通过 httpOnly cookie 下发
    _set_refresh_cookie(response, tokens["refresh_token"])
    return success(TokenOut(
        access_token=tokens["access_token"],
        token_type=tokens["token_type"],
        expires_in=tokens["expires_in"],
    ).model_dump())


@router.post("/refresh", summary="用 refresh cookie 换新 access token(滑动轮换 refresh cookie)")
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    refresh_token = request.cookies.get(settings.REFRESH_COOKIE_NAME)
    try:
        tokens = await auth_service.refresh(db, refresh_token=refresh_token)
    except BusinessError as exc:
        # 失败即清 cookie:失效的 refresh token 不留在浏览器里反复打到本端点
        exc.headers = _delete_refresh_cookie_headers()
        raise
    _set_refresh_cookie(response, tokens["refresh_token"])
    return success(TokenOut(
        access_token=tokens["access_token"],
        token_type=tokens["token_type"],
        expires_in=tokens["expires_in"],
    ).model_dump())


@router.get("/me", summary="当前用户:roles + permissions")
async def me(current: CurrentUser = Depends(get_current_user)):
    data = MeOut(
        id=current.id,
        email=current.email,
        username=current.username,
        name=current.name,
        phone=current.phone,
        must_change_password=current.must_change_password,
        roles=current.roles,
        permissions=current.permissions,
    ).model_dump()
    return success(data)


@router.put("/me", summary="更新当前用户资料(email/username/phone/name)")
async def update_me(
    body: SelfProfileUpdateIn,
    request: Request,
    current: CurrentUser = Depends(block_if_must_change_password),
    db: AsyncSession = Depends(get_db),
):
    user = await user_service.update_self_profile(
        db,
        user_id=current.id,
        actor_user_email=current.email,
        email=body.email,
        username=body.username,
        phone=body.phone,
        name=body.name,
        request=request,
    )
    data = MeOut(
        id=user.id,
        email=user.email,
        username=user.username,
        name=user.name,
        phone=user.phone,
        must_change_password=user.must_change_password,
        roles=current.roles,
        permissions=current.permissions,
    ).model_dump()
    return success(data)


@router.post("/logout", summary="登出(清 refresh cookie,幂等;带有效 token 则写审计)")
async def logout(
    request: Request,
    response: Response,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    # 幂等:access token 缺失/过期也照样清 cookie 返回成功(登出不该失败)。
    # 家族撤销从 refresh cookie 取(即便 access token 已过期也能撤本会话);
    # 仅在 access token 有效时写 LOGOUT 审计(拿得到用户身份)。
    current = None
    if token:
        try:
            current = await get_current_user(token=token, db=db)
        except BusinessError:
            current = None
    await auth_service.logout(
        db,
        refresh_token=request.cookies.get(settings.REFRESH_COOKIE_NAME),
        user_id=current.id if current else None,
        user_email=current.email if current else None,
        request=request,
    )
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        path=settings.REFRESH_COOKIE_PATH,
    )
    return success(None)


@router.post("/change-password", summary="修改自己密码(成功后自动签发新 token)")
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    current: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tokens = await auth_service.change_password(
        db,
        user_id=current.id,
        old_password=body.old_password,
        new_password=body.new_password,
        request=request,
    )
    _set_refresh_cookie(response, tokens["refresh_token"])
    return success(TokenOut(
        access_token=tokens["access_token"],
        token_type=tokens["token_type"],
        expires_in=tokens["expires_in"],
    ).model_dump())
