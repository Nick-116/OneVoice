"""Client IP resolution, optionally behind trusted reverse proxies."""

from __future__ import annotations

from starlette.requests import HTTPConnection

from .config import get_settings


def client_ip(conn: HTTPConnection) -> str:
    """Return the client IP, trusting exactly ``trusted_proxy_hops`` proxies.

    Each trusted proxy appends the address it received the connection from to
    X-Forwarded-For, so the real client is the entry ``hops`` from the right.
    Anything further left is client-controlled and ignored.
    """
    hops = get_settings().trusted_proxy_hops
    peer = conn.client.host if conn.client else "unknown"
    if hops <= 0:
        return peer
    xff = conn.headers.get("x-forwarded-for")
    if not xff:
        return peer
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if len(parts) >= hops:
        return parts[-hops]
    return parts[0] if parts else peer
