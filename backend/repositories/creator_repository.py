"""Creator repository for creator tokens and usage tracking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.repositories.base import BaseRepository


class CreatorRepository(BaseRepository):
    """Repository handling creator_tokens and usage_log tables."""

    def save_token(
        self,
        token_hash: str,
        creator_id: str,
        label: str = "",
    ) -> None:
        """Persist a new hashed creator token."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO creator_tokens (token_hash, creator_id, label, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, creator_id, label, now),
            )

    def get_token(self, token_hash: str) -> dict[str, Any] | None:
        """Retrieve token record by hash."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM creator_tokens WHERE token_hash = ?", (token_hash,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def revoke_token(self, token_hash: str) -> bool:
        """Mark a creator token as revoked."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE creator_tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (now, token_hash),
            )
            return cursor.rowcount > 0

    def touch_token(self, token_hash: str) -> None:
        """Update last_used_at timestamp on token."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE creator_tokens SET last_used_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )

    def log_usage(
        self,
        log_id: str,
        creator_id: str,
        lecture_id: str,
        event_type: str,
        tokens_used: int,
    ) -> None:
        """Record token usage for billing and quotas."""
        now = datetime.now(timezone.utc)
        billing_period = now.strftime("%Y-%m")
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO usage_log (log_id, creator_id, lecture_id, event_type, tokens_used, billing_period, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, creator_id, lecture_id, event_type, tokens_used, billing_period, now.isoformat()),
            )

    def get_monthly_token_usage(self, creator_id: str, billing_period: str | None = None) -> int:
        """Sum tokens used by a creator in the specified or current billing period."""
        period = billing_period or datetime.now(timezone.utc).strftime("%Y-%m")
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT SUM(tokens_used) as total FROM usage_log WHERE creator_id = ? AND billing_period = ?",
                (creator_id, period),
            )
            row = cursor.fetchone()
            if row and row["total"] is not None:
                return int(row["total"])
            return 0

