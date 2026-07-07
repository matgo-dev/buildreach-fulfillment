"""Trace ID 中间件。

每个请求:
- 根据 TRUST_INBOUND_TRACE_ID 配置决定是否读取入站 X-Trace-Id
- 信任模式:读取并校验格式(UUID 或 8-128 位 [A-Za-z0-9_-]),非法则重新生成
- 非信任模式(默认):一律服务端生成,忽略入站头
- 写入 request.state 与 contextvar(供日志/审计读取)
- 在响应头回写 X-Trace-Id
"""
from __future__ import annotations

import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.audit.context import set_trace_id
from app.core.config import settings

# 合法形态:UUID 或反向代理常见的 8-128 位 [A-Za-z0-9_-]
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def _safe_inbound_trace_id(request: Request) -> str | None:
    """信任模式下读取并校验入站 Trace ID;非信任模式返回 None。"""
    if not settings.TRUST_INBOUND_TRACE_ID:
        return None
    raw = request.headers.get("X-Trace-Id")
    return raw if (raw and _TRACE_ID_RE.match(raw)) else None


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = _safe_inbound_trace_id(request) or str(uuid.uuid4())
        request.state.trace_id = trace_id
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response
