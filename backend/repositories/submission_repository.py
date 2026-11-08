"""Submission repository for persisting answers and evaluation results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.repositories.base import BaseRepository


class SubmissionRepository(BaseRepository):
    """Repository handling submissions table."""

    def save_submission(
        self,
        submission_id: str,
        session_id: str,
        intervention_id: str,
        idempotency_key: str,
        user_answer: str,
        status: str,
        resumption_policy: str,
        ai_score: float | None = None,
        is_correct: bool | None = None,
        formative_feedback: str | None = None,
        misconceptions: list[str] | None = None,
        self_assessed: bool = False,
        mastery_applied: bool = False,
        created_at: str | None = None,
        evaluated_at: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        created_str = created_at or datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO submissions (
                    submission_id, session_id, intervention_id, idempotency_key,
                    user_answer, status, resumption_policy, ai_score, is_correct,
                    formative_feedback, misconceptions_json, self_assessed,
                    mastery_applied, created_at, evaluated_at, latency_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(submission_id) DO UPDATE SET
                    status = excluded.status,
                    ai_score = excluded.ai_score,
                    is_correct = excluded.is_correct,
                    formative_feedback = excluded.formative_feedback,
                    misconceptions_json = excluded.misconceptions_json,
                    self_assessed = excluded.self_assessed,
                    mastery_applied = excluded.mastery_applied,
                    evaluated_at = excluded.evaluated_at,
                    latency_ms = excluded.latency_ms
                """,
                (
                    submission_id,
                    session_id,
                    intervention_id,
                    idempotency_key,
                    user_answer,
                    status,
                    resumption_policy,
                    ai_score,
                    1 if is_correct is True else (0 if is_correct is False else None),
                    formative_feedback,
                    json.dumps(misconceptions or []),
                    1 if self_assessed else 0,
                    1 if mastery_applied else 0,
                    created_str,
                    evaluated_at,
                    latency_ms,
                ),
            )

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM submissions WHERE submission_id = ?", (submission_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "submission_id": row["submission_id"],
                "session_id": row["session_id"],
                "intervention_id": row["intervention_id"],
                "idempotency_key": row["idempotency_key"],
                "user_answer": row["user_answer"],
                "status": row["status"],
                "resumption_policy": row["resumption_policy"],
                "ai_score": row["ai_score"],
                "is_correct": bool(row["is_correct"]) if row["is_correct"] is not None else None,
                "formative_feedback": row["formative_feedback"],
                "misconceptions": json.loads(row["misconceptions_json"] or "[]"),
                "self_assessed": bool(row["self_assessed"]),
                "mastery_applied": bool(row["mastery_applied"]),
                "created_at": row["created_at"],
                "evaluated_at": row["evaluated_at"],
                "latency_ms": row["latency_ms"],
            }

    def get_by_idempotency_key(
        self, session_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Find an existing submission by session_id and idempotency_key."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM submissions WHERE session_id = ? AND idempotency_key = ?",
                (session_id, idempotency_key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

