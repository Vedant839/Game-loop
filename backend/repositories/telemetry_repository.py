"""Telemetry repository for recording and exporting engagement and audit events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.repositories.base import BaseRepository


class TelemetryRepository(BaseRepository):
    """Repository handling telemetry_events table."""

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

