"""Per-process request limits and trusted proxy identity helpers."""

from __future__ import annotations

import hashlib

from fastapi import Request
from slowapi import Limiter


def get_real_client_ip(request: Request) -> str:
    """Use the right-most forwarded address appended by the trusted proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        addresses = [part.strip() for part in forwarded.split(",") if part.strip()]
        if addresses:
            return addresses[-1]
    return request.client.host if request.client else "127.0.0.1"


def get_creator_rate_limit_key(request: Request) -> str:
    """Key authenticated creator limits by a digest, never the raw bearer token."""
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() == "bearer" and token:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return f"creator:{digest}"
    return f"ip:{get_real_client_ip(request)}"


limiter = Limiter(
    key_func=get_real_client_ip,
    storage_uri="memory://",
    strategy="fixed-window",
    headers_enabled=False,
)
