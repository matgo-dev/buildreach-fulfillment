"""生产配置 fail-fast 校验。

只拦截 production 下明确不应上线的配置:占位密钥、公开文档、本机对象存储、HTTP/localhost
公网地址、HTTPS 场景下未启用 Secure Cookie/HSTS。非 production 不套这些硬约束。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


_LOCAL_HOST_MARKERS = ("localhost", "127.0.0.1", "0.0.0.0", "minio")


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _is_production(settings: Any) -> bool:
    return _str(getattr(settings, "DEPLOY_ENV", "")).lower() == "production"


def _is_placeholder(value: Any) -> bool:
    raw = _str(value)
    lower = raw.lower()
    if not raw:
        return True
    return (
        lower.startswith("change-me")
        or lower.startswith("changeme")
        or "change_me" in lower
        or "please-change" in lower
        or "<" in raw
        or ">" in raw
    )


def _is_public_https_url(value: Any) -> bool:
    parsed = urlparse(_str(value))
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and bool(host) and host not in _LOCAL_HOST_MARKERS


def _cors_origins(settings: Any) -> list[str]:
    origins = getattr(settings, "CORS_ORIGINS", None)
    if origins is None:
        origins = _str(getattr(settings, "CORS_ORIGINS_RAW", "")).split(",")
    return [_str(origin) for origin in origins if _str(origin)]


def validate_production_settings(settings: Any) -> None:
    """生产环境启动前硬校验;发现错误配置直接抛 RuntimeError 阻止启动。"""
    if not _is_production(settings):
        return

    errors: list[str] = []

    for field in ("JWT_SECRET_KEY", "SUPER_ADMIN_INITIAL_PASSWORD"):
        if _is_placeholder(getattr(settings, field, "")):
            errors.append(f"{field} 不能为空或示例占位值")

    database_url = _str(getattr(settings, "DATABASE_URL", ""))
    if _is_placeholder(database_url) or "change-me" in database_url.lower():
        errors.append("DATABASE_URL 不能包含示例占位密码")

    if bool(getattr(settings, "ENABLE_API_DOCS", False)):
        errors.append("ENABLE_API_DOCS 必须为 false")
    if not bool(getattr(settings, "REFRESH_COOKIE_SECURE", False)):
        errors.append("REFRESH_COOKIE_SECURE 必须为 true")
    if not bool(getattr(settings, "ENABLE_HSTS", False)):
        errors.append("ENABLE_HSTS 必须为 true")
    if _str(getattr(settings, "REFRESH_COOKIE_SAMESITE", "")).lower() not in {"lax", "strict"}:
        errors.append("REFRESH_COOKIE_SAMESITE 必须为 lax 或 strict")

    origins = _cors_origins(settings)
    if not origins:
        errors.append("CORS_ORIGINS 必须配置生产 HTTPS 域名")
    for origin in origins:
        if origin == "*":
            errors.append("CORS_ORIGINS 不能包含 *")
        elif not _is_public_https_url(origin):
            errors.append(f"CORS_ORIGINS 仅允许外部 HTTPS 域名: {origin}")

    if _str(getattr(settings, "STORAGE_BACKEND", "")).lower() != "s3":
        errors.append("STORAGE_BACKEND 必须为 s3")
    if not _is_public_https_url(getattr(settings, "S3_ENDPOINT_URL", "")):
        errors.append("S3_ENDPOINT_URL 必须为外部 HTTPS endpoint")
    for field in ("S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET"):
        if _is_placeholder(getattr(settings, field, "")):
            errors.append(f"{field} 不能为空或示例占位值")

    if errors:
        raise RuntimeError("Production configuration is unsafe: " + "; ".join(errors))
