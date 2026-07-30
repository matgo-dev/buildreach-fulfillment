"""Trace ID + 请求耗时中间件(请求信封唯一入口)。

每个请求:
- 根据 TRUST_INBOUND_TRACE_ID 配置决定是否读取入站 X-Trace-Id
- 信任模式:读取并校验格式(UUID 或 8-128 位 [A-Za-z0-9_-]),非法则重新生成
- 非信任模式(默认):一律服务端生成,忽略入站头
- 写入 request.state 与 contextvar(供日志/审计读取)
- 计时 call_next 全程,完成时按 trace/method/path/status/耗时结构化落一行访问日志
  (供事后 grep trace_id 定位慢请求;/healthz 高频探针不落日志避免刷屏)
- 在响应头回写 X-Trace-Id 与 X-Process-Time-Ms
"""
from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.audit.context import set_trace_id
from app.core.config import settings

logger = logging.getLogger("app.request")

# 合法形态:UUID 或反向代理常见的 8-128 位 [A-Za-z0-9_-]
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _safe_inbound_trace_id(request: Request) -> str | None:
    """信任模式下读取并校验入站 Trace ID;非信任模式返回 None。"""
    if not settings.TRUST_INBOUND_TRACE_ID:
        return None
    raw = request.headers.get("X-Trace-Id")
    # fullmatch 而非 match:`$` 允许尾随一个 \n,"validid\n" 会漏进日志/响应头(h11 拒非法头值 → 500)。
    return raw if (raw and _TRACE_ID_RE.fullmatch(raw)) else None


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = _safe_inbound_trace_id(request) or str(uuid.uuid4())
        request.state.trace_id = trace_id
        set_trace_id(trace_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "%s %s -> 500 in %.1fms", request.method, request.url.path, duration_ms
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
        if request.url.path != "/healthz":
            logger.info(
                "%s %s -> %d in %.1fms",
                request.method, request.url.path, response.status_code, duration_ms,
            )
        return response
