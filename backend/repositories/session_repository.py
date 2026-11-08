"""Session repository for persisting sessions, intervention states, and completed submissions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.repositories.base import BaseRepository


class SessionRepository(BaseRepository):
    """Repository handling sessions and session_interventions tables."""

    def save_session(
        self,
        session_id: str,
        lecture_id: str,
        client_id: str,
        external_user_id: str,
        tier_override: int | None,
        version: int,
        active_intervention_id: str | None,
        active_intervention_tier: int,
        interventions_state: dict[str, str],
        completed_submissions: dict[str, str],
    ) -> None:
        """Persist or update complete runtime session."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, lecture_id, client_id, external_user_id,
                    tier_override, version, active_intervention_id,
                    active_intervention_tier, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    version = excluded.version,
                    active_intervention_id = excluded.active_intervention_id,
                    active_intervention_tier = excluded.active_intervention_tier,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    lecture_id,
                    client_id,
                    external_user_id,
                    tier_override,
                    version,
                    active_intervention_id,
                    active_intervention_tier,
                    now,
                    now,
                ),
            )

            for intv_id, state in interventions_state.items():
                conn.execute(
                    """
                    INSERT INTO session_interventions (session_id, intervention_id, state)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id, intervention_id) DO UPDATE SET
                        state = excluded.state
                    """,
                    (session_id, intv_id, state),
                )

            for idem_key, result_json in completed_submissions.items():
                conn.execute(
                    """
                    INSERT INTO completed_submissions (session_id, idempotency_key, result_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id, idempotency_key) DO UPDATE SET
                        result_json = excluded.result_json
                    """,
                    (session_id, idem_key, result_json),
                )

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load session record with intervention states and completed submissions from SQLite."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            intv_cursor = conn.execute(
                "SELECT intervention_id, state FROM session_interventions WHERE session_id = ?",
                (session_id,),
            )
            interventions_state = {r["intervention_id"]: r["state"] for r in intv_cursor.fetchall()}

            sub_cursor = conn.execute(
                "SELECT idempotency_key, result_json FROM completed_submissions WHERE session_id = ?",
                (session_id,),
            )
            completed_submissions = {
                r["idempotency_key"]: r["result_json"] for r in sub_cursor.fetchall()
            }

            return {
                "session_id": row["session_id"],
                "lecture_id": row["lecture_id"],
                "client_id": row["client_id"],
                "external_user_id": row["external_user_id"],
                "tier_override": row["tier_override"],
                "version": row["version"],
                "active_intervention_id": row["active_intervention_id"],
                "active_intervention_tier": row["active_intervention_tier"],
                "interventions_state": interventions_state,
                "completed_submissions": completed_submissions,
            }

