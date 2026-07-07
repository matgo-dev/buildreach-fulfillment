"""审计日志写入工具。

只记敏感写操作 + 登录相关。GET 请求不应调用本函数。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.constants import AuditAction, AuditResourceType
from app.audit.context import get_trace_id
from app.core.request_ip import get_client_ip
from app.db.models.audit_log import AuditLog, AuditStatus

logger = logging.getLogger(__name__)


async def write_audit(
    db: AsyncSession,
    *,
    resource_type: AuditResourceType | str,
    action: AuditAction | str,
    status: str = AuditStatus.SUCCESS,
    user_id: int | None = None,
    user_email: str | None = None,
    resource_id: str | int | None = None,
    request: Request | None = None,
    error_message: str | None = None,
    extra: dict[str, Any] | None = None,
    commit: bool = True,
) -> None:
    """写一条审计日志。

    commit=True 时自动提交;在更大事务里调用请传 commit=False。
    """
    rt = resource_type.value if isinstance(resource_type, AuditResourceType) else resource_type
    act = action.value if isinstance(action, AuditAction) else action

    method = path = ip = ua = None
    if request is not None:
        method = request.method
        path = str(request.url.path)
        ip = get_client_ip(request)
        ua = request.headers.get("user-agent")

    entry = AuditLog(
        trace_id=get_trace_id(),
        user_id=user_id,
        user_email=user_email,
        resource_type=rt,
        resource_id=str(resource_id) if resource_id is not None else None,
        action=act,
        method=method,
        path=path,
        ip=ip,
        user_agent=ua,
        status=status,
        error_message=error_message,
        extra=extra,
    )
    db.add(entry)
    if commit:
        await db.commit()
    else:
        await db.flush()
