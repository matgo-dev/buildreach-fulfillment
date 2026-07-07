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

        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()

    if request.client is None:
        return "-"
    return request.client.host or "-"
