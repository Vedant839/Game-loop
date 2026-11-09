"""Session repository for persisting sessions, intervention states, and completed submissions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
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
        learner_profile: dict[str, Any] | None = None,
        pending_submission: dict[str, Any] | None = None,
    ) -> None:
        """Persist or update complete runtime session."""
        now = datetime.now(timezone.utc).isoformat()
        statements: list[tuple[str, tuple[Any, ...]]] = [(
            """INSERT INTO sessions (
                session_id, lecture_id, client_id, external_user_id,
                tier_override, version, active_intervention_id,
                active_intervention_tier, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                version = excluded.version,
                active_intervention_id = excluded.active_intervention_id,
                active_intervention_tier = excluded.active_intervention_tier,
                updated_at = excluded.updated_at""",
            (session_id, lecture_id, client_id, external_user_id, tier_override,
             version, active_intervention_id, active_intervention_tier, now, now),
        )]
        statements.extend((
            """INSERT INTO session_interventions (session_id, intervention_id, state)
               VALUES (?, ?, ?) ON CONFLICT(session_id, intervention_id) DO UPDATE SET
               state = excluded.state""",
            (session_id, intervention_id, state),
        ) for intervention_id, state in interventions_state.items())
        statements.extend((
            """INSERT INTO completed_submissions (session_id, idempotency_key, result_json)
               VALUES (?, ?, ?) ON CONFLICT(session_id, idempotency_key) DO UPDATE SET
               result_json = excluded.result_json""",
            (session_id, key, value),
        ) for key, value in completed_submissions.items())
        if pending_submission is not None:
            statements.append((
                """INSERT INTO submissions (
                    submission_id, session_id, intervention_id, idempotency_key,
                    user_answer, status, resumption_policy, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (pending_submission["submission_id"], pending_submission["session_id"],
                 pending_submission["intervention_id"], pending_submission["idempotency_key"],
                 pending_submission["user_answer"], pending_submission["status"],
                 pending_submission["resumption_policy"], pending_submission["created_at"]),
            ))
        if learner_profile is not None:
            statements.append((
                """INSERT INTO learner_profiles (
                    client_id, user_id, concept_mastery_json, streak, friction_index,
                    total_interventions, total_correct, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id, user_id) DO UPDATE SET
                    concept_mastery_json = excluded.concept_mastery_json,
                    streak = excluded.streak,
                    friction_index = excluded.friction_index,
                    total_interventions = excluded.total_interventions,
                    total_correct = excluded.total_correct,
                    updated_at = excluded.updated_at""",
                (learner_profile["client_id"], learner_profile["user_id"],
                 json.dumps(learner_profile["concept_mastery"]), learner_profile["streak"],
                 learner_profile["friction_index"], learner_profile["total_interventions"],
                 learner_profile["total_correct"], datetime.now(timezone.utc).isoformat()),
            ))
        self.db.execute_batch(statements)

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load session record with intervention states and completed submissions from SQLite."""
        if self.db.backend == "sqlite":
            with self.db.connection() as conn:
                session_rows = [dict(row) for row in conn.execute(
                    "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchall()]
                intervention_rows = [dict(row) for row in conn.execute(
                    "SELECT intervention_id, state FROM session_interventions WHERE session_id = ?",
                    (session_id,),
                ).fetchall()]
                submission_rows = [dict(row) for row in conn.execute(
                    "SELECT idempotency_key, result_json FROM completed_submissions WHERE session_id = ?",
                    (session_id,),
                ).fetchall()]
        else:
            statements = [
                ("SELECT * FROM sessions WHERE session_id = ?", (session_id,)),
                ("SELECT intervention_id, state FROM session_interventions WHERE session_id = ?", (session_id,)),
                ("SELECT idempotency_key, result_json FROM completed_submissions WHERE session_id = ?", (session_id,)),
            ]
            results = self.db.execute_batch(statements, transactional=False)

            def rows_as_dicts(result: Any) -> list[dict[str, Any]]:
                columns = [description[0] for description in result.description or ()]
                return [dict(zip(columns, row)) for row in result.fetchall()]

            session_rows, intervention_rows, submission_rows = map(rows_as_dicts, results)
        if not session_rows:
            return None
        row = session_rows[0]
        interventions_state = {r["intervention_id"]: r["state"] for r in intervention_rows}
        completed_submissions = {
            r["idempotency_key"]: r["result_json"] for r in submission_rows
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

    def list_sessions_by_creator(
        self, creator_id: str, lecture_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Return session identifiers and lecture metadata for one creator."""
        bounded_limit = max(1, min(limit, 500))
        with self.db.connection() as conn:
            if lecture_id is None:
                cursor = conn.execute(
                    """SELECT session_id, lecture_id, created_at, updated_at
                       FROM sessions WHERE client_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (creator_id, bounded_limit),
                )
            else:
                cursor = conn.execute(
                    """SELECT session_id, lecture_id, created_at, updated_at
                       FROM sessions WHERE client_id = ? AND lecture_id = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (creator_id, lecture_id, bounded_limit),
                )
            return [dict(row) for row in cursor.fetchall()]

