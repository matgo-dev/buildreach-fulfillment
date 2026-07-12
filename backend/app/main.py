"""FastAPI 入口:中间件、异常处理、lifespan(同步 RBAC + 引导管理员)。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.audit.context import get_trace_id
from app.audit.middleware import RequestIDMiddleware
from app.core.config import settings
from app.core.exceptions import BusinessError, success
from app.core.message_keys import MessageKey
from app.core.logging_config import setup_logging
from app.db.session import AsyncSessionLocal
from app.rbac.sync import sync_rbac
from app.seed import run_all_seeds

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("App starting up...")
    async with AsyncSessionLocal() as db:
        await sync_rbac(db)
        await run_all_seeds(db)
    logger.info("App startup complete.")
    yield
    logger.info("App shutting down.")


app = FastAPI(
    title="公司内部供应链履约系统 · API",
    version="0.1.0",
    description="M0 地基:认证、RBAC、审计、存储",
    lifespan=lifespan,
)

if "*" in settings.CORS_ORIGINS:
    raise RuntimeError("CORS_ORIGINS 不能含 `*`(带凭证时浏览器拒收)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"], allow_headers=["*"],
    expose_headers=["X-Trace-Id", "Content-Disposition"],
)
app.add_middleware(RequestIDMiddleware)


@app.exception_handler(BusinessError)
async def biz_exc_handler(request: Request, exc: BusinessError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={
        "code": exc.biz_code, "message": exc.biz_message,
        "message_key": exc.message_key,
        "message_params": getattr(exc, "message_params", None),
        "data": exc.biz_data, "trace_id": get_trace_id()})


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=jsonable_encoder({
        "code": 42200, "message": "Validation error",
        "message_key": MessageKey.VALIDATION_FAILED, "message_params": None,
        "data": {"errors": exc.errors()}, "trace_id": get_trace_id()}))


@app.exception_handler(StarletteHTTPException)
async def http_exc_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={
        "code": 40000, "message": str(exc.detail) if exc.detail else "Error",
        "message_key": MessageKey.CLIENT_ERROR, "message_params": None,
        "data": None, "trace_id": get_trace_id()})


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={
        "code": 50000, "message": "Internal server error",
        "message_key": MessageKey.INTERNAL_ERROR, "message_params": None,
        "data": None, "trace_id": get_trace_id()})


@app.get("/healthz", tags=["system"])
async def healthz():
    return success({"status": "ok"})


from app.api.v1.router import api_router  # noqa: E402
app.include_router(api_router)

# 商品图本地读取(根路径 /media,非 /api/v1;仅 local 后端生效)。
from app.api.media import router as media_router  # noqa: E402
app.include_router(media_router)
