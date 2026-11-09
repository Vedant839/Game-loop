"""Import local lecture JSON files into the V0.4 lectures table.

This is an explicit setup command and is never called during application boot.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import get_settings


def _source_type(video_url: str) -> str:
    lowered = video_url.lower()
    if "youtube.com/" in lowered or "youtu.be/" in lowered:
        return "youtube"
    if "vimeo.com/" in lowered:
        return "vimeo"
    return "direct"


def _lecture_values(path: Path, creator_id: str) -> tuple[Any, ...]:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid lecture JSON file {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Lecture JSON file {path.name} must contain an object")

    lecture_id = data.get("id")
    title = data.get("title")
    video_url = data.get("video_url")
    if not all(isinstance(value, str) and value.strip() for value in (lecture_id, title, video_url)):
        raise ValueError(
            f"Lecture JSON file {path.name} requires non-empty string fields: id, title, video_url"
        )

    now = datetime.now(timezone.utc).isoformat()
    return (
        lecture_id,
        creator_id,
        None,
        title,
        video_url,
        _source_type(video_url),
        str(data.get("intensity", "standard")),
        json.dumps(data.get("branding"), ensure_ascii=False, separators=(",", ":"))
        if data.get("branding") is not None
        else None,
        raw,
        now,
        now,
    )


UPSERT_LECTURE = """
    INSERT INTO lectures (
        lecture_id, creator_id, course_id, title, video_url, source_type,
        intensity, branding, content, created_at, updated_at
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
    WHERE lectures.creator_id IS NOT excluded.creator_id
       OR lectures.course_id IS NOT excluded.course_id
       OR lectures.title IS NOT excluded.title
       OR lectures.video_url IS NOT excluded.video_url
       OR lectures.source_type IS NOT excluded.source_type
       OR lectures.intensity IS NOT excluded.intensity
       OR lectures.branding IS NOT excluded.branding
       OR lectures.content IS NOT excluded.content
"""


def backfill_lectures(
    conn: Any,
    lecture_dir: Path | str,
    creator_id: str = "default_client",
) -> int:
    """Upsert JSON files in *lecture_dir* in one transaction; return changed row count."""
    directory = Path(lecture_dir)
    files = sorted(directory.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No lecture JSON files found in {directory}")

    try:
        conn.execute("BEGIN")
        changed = 0
        for path in files:
            values = _lecture_values(path, creator_id)
            cursor = conn.execute(UPSERT_LECTURE, values)
            changed += max(cursor.rowcount, 0)
        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill local lecture JSON into the lectures table")
    parser.add_argument("--lectures-dir", type=Path, default=get_settings().lectures_dir)
    parser.add_argument("--db", type=Path, help="SQLite database to update; required for SQLite")
    parser.add_argument("--creator-id", default="default_client")
    args = parser.parse_args()

    settings = get_settings()
    if settings.database_backend.lower() == "turso":
        if not settings.turso_database_url or not settings.turso_auth_token:
            parser.error("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required for Turso")
        import turso_serverless

        from backend.database import _install_turso_request_timeout

        conn = turso_serverless.connect(
            settings.turso_database_url,
            auth_token=settings.turso_auth_token.get_secret_value(),
        )
        _install_turso_request_timeout(conn, settings.database_timeout_seconds)
    else:
        if args.db is None:
            parser.error("Pass --db explicitly to select the SQLite database to update")
        conn = sqlite3.connect(args.db, timeout=settings.database_timeout_seconds)

    try:
        count = backfill_lectures(conn, args.lectures_dir, args.creator_id)
    finally:
        conn.close()
    print(f"Backfilled {count} lecture row(s) from {args.lectures_dir}")


if __name__ == "__main__":
    main()
