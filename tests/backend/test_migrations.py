"""Migration regression against the committed, data-free V0.3 schema fixture."""

import sqlite3
from pathlib import Path

from scripts.migrate import migrate_database


FIXTURE = Path(__file__).parents[1] / "fixtures" / "v03_schema.sql"


def test_v03_migration_is_guarded_and_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "v03_fixture.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(FIXTURE.read_text(encoding="utf-8"))
        conn.execute(
            """INSERT INTO sessions (
                session_id, lecture_id, client_id, external_user_id, created_at, updated_at
            ) VALUES ('s1', 'linux_lecture', 'default_client', 'learner_1', 'created', 'updated')"""
        )
        conn.execute(
            "INSERT INTO session_interventions (session_id, intervention_id, state) "
            "VALUES ('s1', 'i1', 'BYPASSED')"
        )

    assert migrate_database(db_path) is True
    with sqlite3.connect(db_path) as conn:
        version_rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        assert version_rows == [(1,)]
        session = conn.execute(
            "SELECT creator_id, learner_id FROM sessions WHERE session_id = 's1'"
        ).fetchone()
        assert session == ("default_client", "learner_1")
        intervention = conn.execute(
            "SELECT lecture_id, state FROM session_interventions WHERE session_id = 's1'"
        ).fetchone()
        assert intervention == ("linux_lecture", "BYPASSED")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(session_interventions)")}
        assert {"revision", "attempt_count", "hint_used", "first_try_correct"} <= columns
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"creator_tokens", "usage_log", "courses", "lectures", "course_lectures", "study_guides", "tab_events"} <= tables
        schema_before_second_run = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()

    assert migrate_database(db_path) is False
    with sqlite3.connect(db_path) as conn:
        schema_after_second_run = conn.execute(
            "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
        ).fetchall()
        assert schema_after_second_run == schema_before_second_run
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone() == (1,)
        assert conn.execute("SELECT COUNT(*) FROM session_interventions").fetchone() == (1,)
