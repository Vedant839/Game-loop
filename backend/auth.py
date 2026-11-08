"""Creator token authentication helpers."""

from __future__ import annotations

import hashlib

from fastapi import Header, HTTPException, status

from backend.database import get_database


def require_creator(authorization: str | None = Header(default=None)) -> dict[str, str]:
    """Validate a bearer token and return its creator record."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Creator token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw_token = authorization.removeprefix("Bearer ").strip()
    if not raw_token:
        raise HTTPException(status_code=401, detail="Invalid creator token")

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    try:
        record = get_database().creators.get_token(token_hash)
    except Exception:
        record = None
    if not record or record.get("revoked_at") is not None:
        raise HTTPException(status_code=401, detail="Invalid creator token")
    get_database().creators.touch_token(token_hash)
    return record
