"""Lecture repository for persisting courses and lecture JSON content."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.repositories.base import BaseRepository


class LectureRepository(BaseRepository):
    """Repository handling courses, course_lectures, and lectures tables."""

    def save_lecture(
        self,
        lecture_id: str,
        creator_id: str,
        title: str,
        video_url: str,
        source_type: str,
        content_json: str,
        course_id: str | None = None,
        intensity: str = "standard",
        branding_json: str | None = None,
    ) -> None:
        """Persist or update lecture record."""
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO lectures (
                    lecture_id, creator_id, course_id, title, video_url,
                    source_type, intensity, branding, content, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(lecture_id) DO UPDATE SET
                    creator_id = excluded.creator_id,
                    course_id = excluded.course_id,
                    title = excluded.title,
                    video_url = excluded.video_url,
                    source_type = excluded.source_type,
                    intensity = excluded.intensity,
                    branding = excluded.branding,
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (
                    lecture_id,
                    creator_id,
                    course_id,
                    title,
                    video_url,
                    source_type,
                    intensity,
                    branding_json,
                    content_json,
                    now,
                    now,
                ),
            )

    def get_lecture(self, lecture_id: str) -> dict[str, Any] | None:
        """Load lecture record from database."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM lectures WHERE lecture_id = ?", (lecture_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def list_lectures_by_creator(self, creator_id: str) -> list[dict[str, Any]]:
        """List all lectures belonging to a creator."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM lectures WHERE creator_id = ? ORDER BY updated_at DESC",
                (creator_id,),
            )
            return [dict(r) for r in cursor.fetchall()]

