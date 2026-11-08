"""Idempotent, offline migration runner for the V0.3 SQLite schema."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.config import get_settings

MIGRATION_VERSION = 1
BASELINE_TABLES = {
    "sessions",
    "session_interventions",
    "submissions",
    "learner_profiles",
    "telemetry_events",
    "completed_submissions",
    "tenants",
}

COLUMNS_TO_ADD: dict[str, tuple[tuple[str, str], ...]] = {
    "sessions": (
        ("creator_id", "TEXT DEFAULT 'default_client'"),
        ("learner_id", "TEXT DEFAULT 'default_learner'"),
        ("course_id", "TEXT"),
        ("is_preview", "INTEGER NOT NULL DEFAULT 0"),
    ),
    "session_interventions": (
        ("lecture_id", "TEXT NOT NULL DEFAULT ''"),
        ("revision", "INTEGER NOT NULL DEFAULT 1"),
        ("attempt_count", "INTEGER NOT NULL DEFAULT 0"),
        ("hint_used", "INTEGER NOT NULL DEFAULT 0"),
        ("first_try_correct", "INTEGER DEFAULT NULL"),
        ("activated_at", "TEXT"),
        ("completed_at", "TEXT"),
    ),
    "submissions": (
        ("revision", "INTEGER NOT NULL DEFAULT 1"),
        ("raw_answer", "TEXT"),
        ("reflect_text", "TEXT"),
        ("flag_for_review", "INTEGER NOT NULL DEFAULT 0"),
        ("client_reported", "INTEGER NOT NULL DEFAULT 0"),
    ),
    "telemetry_events": (("lecture_id", "TEXT NOT NULL DEFAULT ''"),),
}

NEW_TABLES = (
    """CREATE TABLE IF NOT EXISTS creator_tokens (
        token_hash TEXT PRIMARY KEY,
        creator_id TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS usage_log (
        log_id TEXT PRIMARY KEY,
        creator_id TEXT NOT NULL,
        lecture_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        tokens_used INTEGER NOT NULL,
        billing_period TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS courses (
        course_id TEXT PRIMARY KEY,
        creator_id TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS lectures (
        lecture_id TEXT PRIMARY KEY,
        creator_id TEXT NOT NULL,
        course_id TEXT,
        title TEXT NOT NULL,
        video_url TEXT NOT NULL,
        source_type TEXT NOT NULL,
        intensity TEXT NOT NULL DEFAULT 'standard',
        branding TEXT,
        content TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS course_lectures (
        course_id TEXT NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
        lecture_id TEXT NOT NULL REFERENCES lectures(lecture_id) ON DELETE CASCADE,
        position INTEGER NOT NULL,
        PRIMARY KEY (course_id, lecture_id)
    )""",
    """CREATE TABLE IF NOT EXISTS study_guides (
        guide_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL UNIQUE REFERENCES sessions(session_id) ON DELETE CASCADE,
        content_md TEXT NOT NULL,
        generated_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tab_events (
        event_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,
        playback_position REAL,
        away_seconds REAL,
        created_at TEXT NOT NULL
    )""",
)

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_sessions_lecture ON sessions(lecture_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_creator ON sessions(creator_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_learner ON sessions(learner_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_preview ON sessions(is_preview)",
    "CREATE INDEX IF NOT EXISTS idx_session_intv_radar ON session_interventions(lecture_id, intervention_id, revision, state)",
    "CREATE INDEX IF NOT EXISTS idx_submissions_session ON submissions(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_usage_log_creator_period ON usage_log(creator_id, billing_period)",
    "CREATE INDEX IF NOT EXISTS idx_creator_tokens_hash ON creator_tokens(token_hash)",
    "CREATE INDEX IF NOT EXISTS idx_tab_events_session ON tab_events(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_telemetry_lecture ON telemetry_events(lecture_id, event_type)",
)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in present:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def migrate_database(db_path: Path | str) -> bool:
    """Apply V0.4 schema once. Return True only when a migration was applied."""
    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(f"Database does not exist: {path}")

    conn = sqlite3.connect(path, timeout=30.0)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT NOT NULL
            )"""
        )
        if conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (MIGRATION_VERSION,)
        ).fetchone():
            conn.commit()
            return False

        missing = BASELINE_TABLES - _table_names(conn)
        if missing:
            raise RuntimeError(
                "Refusing to migrate a database without the V0.3 baseline tables: "
                + ", ".join(sorted(missing))
            )

        for table, columns in COLUMNS_TO_ADD.items():
            for column, declaration in columns:
                _add_column_if_missing(conn, table, column, declaration)

        for statement in NEW_TABLES:
            conn.execute(statement)

        # The migration version guard makes each backfill a one-time operation.
        # The value checks also restrict updates to legacy/defaulted V0.3 rows.
        conn.execute(
            """UPDATE sessions
               SET creator_id = COALESCE(client_id, 'default_client'),
                   learner_id = COALESCE(external_user_id, 'legacy')
               WHERE creator_id IN ('default_client', 'default_creator')
                 AND learner_id = 'default_learner'
                 AND NOT EXISTS (
                     SELECT 1 FROM schema_migrations WHERE version = ?
                 )""",
            (MIGRATION_VERSION,),
        )
        conn.execute(
            """UPDATE session_interventions
               SET lecture_id = (
                   SELECT lecture_id FROM sessions
                   WHERE sessions.session_id = session_interventions.session_id
               )
               WHERE lecture_id = ''
                 AND EXISTS (
                     SELECT 1 FROM sessions
                     WHERE sessions.session_id = session_interventions.session_id
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM schema_migrations WHERE version = ?
                 )""",
            (MIGRATION_VERSION,),
        )

        for statement in INDEXES:
            conn.execute(statement)

        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at, description) "
            "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?)",
            (MIGRATION_VERSION, "V0.4 incremental schema and legacy backfill"),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply game-loop database migrations")
    parser.add_argument(
        "--db",
        type=Path,
        default=get_settings().db_path,
        help="SQLite database path (defaults to GAME_LOOP_DB_PATH)",
    )
    args = parser.parse_args()
    applied = migrate_database(args.db)
    if applied:
        print(f"Applied migration {MIGRATION_VERSION} to {args.db}")
    else:
        print(f"Database already at migration {MIGRATION_VERSION}; no changes made")


if __name__ == "__main__":
    main()
