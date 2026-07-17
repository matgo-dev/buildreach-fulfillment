"""认证路由 /api/v1/auth/*(login/refresh/change-password/logout/me)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import CurrentUser, get_current_user, oauth2_scheme
from app.core.exceptions import BusinessError, success
from app.db.session import get_db
from app.schemas.auth import ChangePasswordIn, LoginIn, MeOut, TokenOut
from app.services import auth_service

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
        name=current.name,
        must_change_password=current.must_change_password,
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
    # 幂等:access token 缺失/过期也照样清 cookie 返回成功(登出不该失败);
    # 仅在 token 有效时写 LOGOUT 审计。
    if token:
        try:
            current = await get_current_user(token=token, db=db)
        except BusinessError:
            current = None
        if current is not None:
            await auth_service.logout(
                db, user_id=current.id, user_email=current.email, request=request
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
