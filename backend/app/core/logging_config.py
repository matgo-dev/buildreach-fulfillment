"""日志配置:格式 `[time] [trace=xxx] [LEVEL] logger: message`。"""
from __future__ import annotations

import logging
import sys

from app.audit.context import get_trace_id
from app.core.config import settings


class TraceIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


def setup_logging() -> None:
    fmt = "[%(asctime)s] [trace=%(trace_id)s] [%(levelname)s] %(name)s: %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%SZ"))
    handler.addFilter(TraceIDFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())

    # 静默过吵的库
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.ERROR)
