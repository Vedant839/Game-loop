"""Telemetry repository for recording and exporting engagement and audit events."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.repositories.base import BaseRepository


class TelemetryRepository(BaseRepository):
    """Repository handling telemetry_events table."""

    def latest_tab_recall(self, session_id: str) -> str | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT created_at FROM tab_events WHERE session_id = ? AND event_type = ? ORDER BY created_at DESC LIMIT 1",
                (session_id, "recall_shown"),
            ).fetchone()
        return row["created_at"] if row else None

    def record_tab_recall(self, session_id: str, away_seconds: float) -> None:
        with self.db.connection() as conn:
            conn.execute(
                "INSERT INTO tab_events (event_id, session_id, event_type, playback_position, away_seconds, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), session_id, "recall_shown", None, away_seconds, datetime.now(timezone.utc).isoformat()),
            )

    def record_telemetry(
        self,
        client_id: str,
        session_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        ts = timestamp or datetime.now(timezone.utc).timestamp()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO telemetry_events (
                    client_id, session_id, user_id, event_type, payload_json, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (client_id, session_id, user_id, event_type, json.dumps(payload), ts),
            )

    def export_telemetry(
        self, client_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            if client_id:
                cursor = conn.execute(
                    "SELECT * FROM telemetry_events WHERE client_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (client_id, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM telemetry_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": r["id"],
                    "client_id": r["client_id"],
                    "session_id": r["session_id"],
                    "user_id": r["user_id"],
                    "event_type": r["event_type"],
                    "payload": json.loads(r["payload_json"]),
                    "timestamp": r["timestamp"],
                }
                for r in rows
            ]

