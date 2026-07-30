"""Client IP extraction helpers."""
from __future__ import annotations

from starlette.requests import Request

from app.core.config import settings


def get_client_ip(request: Request | None) -> str:
    """Return client IP, optionally trusting headers from a known reverse proxy."""
    if request is None:
        return "-"

    if settings.TRUST_PROXY:
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        # X-Real-IP 缺失时才回落 XFF,且取**最右**跳:XFF 是「client, proxy1, ...」链,最左值
        # 由客户端原样送入(nginx `$proxy_add_x_forwarded_for` 是追加非覆盖),可伪造;最右是
        # 紧邻本服务的可信反代追加的、它实际看到的连接方 IP。取最左会让限流键/审计 IP 被伪造。
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.rsplit(",", 1)[-1].strip()

    if request.client is None:
        return "-"
    return request.client.host or "-"
