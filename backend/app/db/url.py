"""DATABASE_URL 规范化:兼容 Neon / Render 等托管 PG 与本地裸 URL。

云上 PG 常给 `postgresql://user:pwd@host/db?sslmode=require` 这种 libpq 风格 URL,
- async 引擎(asyncpg)需要 `postgresql+asyncpg://`,且不认识 `sslmode` 参数(要用 connect_args.ssl)
- sync 引擎(psycopg v3)需要 `postgresql+psycopg://`,本身认识 `sslmode`
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def prepare_async_url(dsn: str) -> tuple[str, dict]:
    """返回 (asyncpg DSN, connect_args)。把 sslmode 剥离到 connect_args.ssl。"""
    if dsn.startswith("postgresql://"):
        dsn = "postgresql+asyncpg://" + dsn[len("postgresql://"):]

    parsed = urlparse(dsn)
    params = dict(parse_qsl(parsed.query))
    connect_args: dict = {}

    sslmode = params.pop("sslmode", None)
    if sslmode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = True
    elif sslmode in ("disable", "allow", "prefer"):
        connect_args["ssl"] = False

    # channel_binding 也是 libpq 专属,asyncpg 不识别
    params.pop("channel_binding", None)

    new_dsn = urlunparse(parsed._replace(query=urlencode(params)))
    return new_dsn, connect_args


def prepare_sync_url(dsn: str) -> str:
    """返回 psycopg(v3) DSN,sslmode 等参数原样保留。"""
    if dsn.startswith("postgresql+asyncpg://"):
        return "postgresql+psycopg://" + dsn[len("postgresql+asyncpg://"):]
    if dsn.startswith("postgresql://"):
        return "postgresql+psycopg://" + dsn[len("postgresql://"):]
    return dsn
