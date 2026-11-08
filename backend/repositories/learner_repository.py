"""Learner repository for persisting mastery, streaks, and engagement metrics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.repositories.base import BaseRepository


class LearnerRepository(BaseRepository):
    """Repository handling learner_profiles table."""

    def save_learner_profile(
        self,
        client_id: str,
        user_id: str,
        concept_mastery: dict[str, float],
        streak: int,
        friction_index: float,
        total_interventions: int,
        total_correct: int,
    ) -> None:
        """Persist learner profile."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO learner_profiles (
                    client_id, user_id, concept_mastery_json, streak,
                    friction_index, total_interventions, total_correct, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id, user_id) DO UPDATE SET
                    concept_mastery_json = excluded.concept_mastery_json,
                    streak = excluded.streak,
                    friction_index = excluded.friction_index,
                    total_interventions = excluded.total_interventions,
                    total_correct = excluded.total_correct,
                    updated_at = excluded.updated_at
                """,
                (
                    client_id,
                    user_id,
                    json.dumps(concept_mastery),
                    streak,
                    friction_index,
                    total_interventions,
                    total_correct,
                    now,
                ),
            )

    def load_learner_profile(self, client_id: str, user_id: str) -> dict[str, Any] | None:
        """Load learner profile from database."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM learner_profiles WHERE client_id = ? AND user_id = ?",
                (client_id, user_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "client_id": row["client_id"],
                "user_id": row["user_id"],
                "concept_mastery": json.loads(row["concept_mastery_json"]),
                "streak": row["streak"],
                "friction_index": row["friction_index"],
                "total_interventions": row["total_interventions"],
                "total_correct": row["total_correct"],
            }

