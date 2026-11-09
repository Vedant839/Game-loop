"""Embedded SQLite persistence manager for game-loop V0.3."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from backend.config import get_settings
from backend.repositories.creator_repository import CreatorRepository
from backend.repositories.learner_repository import LearnerRepository
from backend.repositories.lecture_repository import LectureRepository
from backend.repositories.session_repository import SessionRepository
from backend.repositories.submission_repository import SubmissionRepository
from backend.repositories.telemetry_repository import TelemetryRepository

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe SQLite database manager for game-loop sessions, profiles, and telemetry."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            settings = get_settings()
            self.db_path = settings.db_path
        else:
            self.db_path = Path(db_path)

        # Ensure parent directory exists (e.g. data/)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.backend = get_settings().database_backend.lower()
        self._lock = threading.Lock()
        self._init_db()

        # Repositories
        self.sessions = SessionRepository(self)
        self.submissions = SubmissionRepository(self)
        self.learners = LearnerRepository(self)
        self.telemetry = TelemetryRepository(self)
        self.lectures = LectureRepository(self)
        self.creators = CreatorRepository(self)

    @contextmanager
    def connection(self) -> Generator[Any, None, None]:
        if self.backend == "turso":
            settings = get_settings()
            if not settings.turso_database_url or not settings.turso_auth_token:
                raise RuntimeError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required for Turso")
            try:
                import turso_serverless
            except ImportError as exc:
                raise RuntimeError("Install turso-serverless to use the Turso backend") from exc
            conn = turso_serverless.connect(
                settings.turso_database_url,
                auth_token=settings.turso_auth_token.get_secret_value(),
            )
            conn.row_factory = turso_serverless.Row
        elif self.backend == "sqlite":
            conn = sqlite3.connect(
                str(self.db_path), check_same_thread=False, timeout=30.0
            )
            conn.row_factory = sqlite3.Row
        else:
            raise ValueError(f"Unsupported database backend: {self.backend}")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute_batch(
        self,
        statements: list[tuple[str, tuple[Any, ...]]],
        *,
        transactional: bool = True,
    ) -> list[Any]:
        """Run ordered statements on one connection.

        turso-serverless 0.1.0 has no ``Connection.batch``. Each ``execute``
        is its own ``POST /v3/cursor``. The connection's session baton keeps
        one server transaction open across those calls when implicit BEGIN is
        enabled; ``connection()`` then commits it, or rolls it back if any
        statement raises. A transactional DML batch of N statements therefore
        costs N + 3 HTTP requests: BEGIN, N statements, COMMIT, and stream
        close. A non-transactional batch does not BEGIN or COMMIT, so it costs
        N statement requests plus close, and earlier statements stay applied
        if a later one fails.
        """
        with self.connection() as conn:
            if self.backend == "turso" and not transactional:
                conn.isolation_level = None
            return [conn.execute(sql, parameters) for sql, parameters in statements]

    def _execute_script(self, conn: Any, script: str) -> None:
        """Execute DDL. Turso's public executescript is one pipeline POST."""
        if self.backend == "turso":
            conn.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                conn.execute(statement)

    def _init_db(self) -> None:
        """Create tables and initialize WAL mode."""
        with self._lock:
            with self.connection() as conn:
                if self.backend == "sqlite":
                    if str(self.db_path) != ":memory:":
                        conn.execute("PRAGMA journal_mode = WAL;")
                    conn.execute("PRAGMA synchronous = NORMAL;")
                    conn.execute("PRAGMA foreign_keys = ON;")

                self._execute_script(
                    conn,
                    """
                    CREATE TABLE IF NOT EXISTS tenants (
                        client_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        default_policy TEXT NOT NULL DEFAULT 'skippable',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        lecture_id TEXT NOT NULL,
                        client_id TEXT NOT NULL DEFAULT 'default_client',
                        external_user_id TEXT NOT NULL DEFAULT 'default_learner',
                        tier_override INTEGER,
                        version INTEGER NOT NULL DEFAULT 1,
                        active_intervention_id TEXT,
                        active_intervention_tier INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS session_interventions (
                        session_id TEXT NOT NULL,
                        intervention_id TEXT NOT NULL,
                        state TEXT NOT NULL,
                        PRIMARY KEY (session_id, intervention_id),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS completed_submissions (
                        session_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        result_json TEXT NOT NULL,
                        PRIMARY KEY (session_id, idempotency_key),
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS submissions (
                        submission_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        intervention_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        user_answer TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'pending',
                        resumption_policy TEXT NOT NULL DEFAULT 'immediate_optimistic',
                        ai_score REAL,
                        is_correct INTEGER,
                        formative_feedback TEXT,
                        misconceptions_json TEXT DEFAULT '[]',
                        self_assessed INTEGER NOT NULL DEFAULT 0,
                        mastery_applied INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        evaluated_at TEXT,
                        latency_ms INTEGER,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS learner_profiles (
                        client_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        concept_mastery_json TEXT NOT NULL,
                        streak INTEGER NOT NULL DEFAULT 0,
                        friction_index REAL NOT NULL DEFAULT 1.0,
                        total_interventions INTEGER NOT NULL DEFAULT 0,
                        total_correct INTEGER NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (client_id, user_id)
                    );

                    CREATE TABLE IF NOT EXISTS telemetry_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        client_id TEXT NOT NULL,
                        session_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        timestamp REAL NOT NULL
                    );
                    """
                )
        logger.info("Database initialized at %s", self.db_path)

    # -------------------------------------------------------------------------
    # Sessions Persistence (delegates to SessionRepository)
    # -------------------------------------------------------------------------

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
        with self._lock:
            self.sessions.save_session(
                session_id=session_id,
                lecture_id=lecture_id,
                client_id=client_id,
                external_user_id=external_user_id,
                tier_override=tier_override,
                version=version,
                active_intervention_id=active_intervention_id,
                active_intervention_tier=active_intervention_tier,
                interventions_state=interventions_state,
                completed_submissions=completed_submissions,
                learner_profile=learner_profile,
                pending_submission=pending_submission,
            )

    def load_session(self, session_id: str) -> dict[str, Any] | None:
        """Load session record with intervention states and completed submissions."""
        return self.sessions.load_session(session_id)

    # -------------------------------------------------------------------------
    # Learner Profile Persistence (delegates to LearnerRepository)
    # -------------------------------------------------------------------------

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
        with self._lock:
            self.learners.save_learner_profile(
                client_id=client_id,
                user_id=user_id,
                concept_mastery=concept_mastery,
                streak=streak,
                friction_index=friction_index,
                total_interventions=total_interventions,
                total_correct=total_correct,
            )

    def load_learner_profile(self, client_id: str, user_id: str) -> dict[str, Any] | None:
        """Load learner profile from database."""
        return self.learners.load_learner_profile(client_id, user_id)

    # -------------------------------------------------------------------------
    # Submissions & Open-Ended Evaluations (delegates to SubmissionRepository)
    # -------------------------------------------------------------------------

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
        with self._lock:
            self.submissions.save_submission(
                submission_id=submission_id,
                session_id=session_id,
                intervention_id=intervention_id,
                idempotency_key=idempotency_key,
                user_answer=user_answer,
                status=status,
                resumption_policy=resumption_policy,
                ai_score=ai_score,
                is_correct=is_correct,
                formative_feedback=formative_feedback,
                misconceptions=misconceptions,
                self_assessed=self_assessed,
                mastery_applied=mastery_applied,
                created_at=created_at,
                evaluated_at=evaluated_at,
                latency_ms=latency_ms,
            )

    def get_submission(self, submission_id: str) -> dict[str, Any] | None:
        return self.submissions.get_submission(submission_id)

    # -------------------------------------------------------------------------
    # Telemetry (delegates to TelemetryRepository)
    # -------------------------------------------------------------------------

    def record_telemetry(
        self,
        client_id: str,
        session_id: str,
        user_id: str,
        event_type: str,
        payload: dict[str, Any],
        timestamp: float | None = None,
    ) -> None:
        with self._lock:
            self.telemetry.record_telemetry(
                client_id=client_id,
                session_id=session_id,
                user_id=user_id,
                event_type=event_type,
                payload=payload,
                timestamp=timestamp,
            )


    def delete_learner(self, client_id: str, user_id: str) -> int:
        """Atomically remove a learner, their sessions, submissions, and telemetry."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT session_id FROM sessions WHERE client_id = ? AND external_user_id = ?",
                (client_id, user_id),
            ).fetchall()
            session_ids = [row["session_id"] for row in rows]
            for session_id in session_ids:
                conn.execute("DELETE FROM completed_submissions WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM session_interventions WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM submissions WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            conn.execute(
                "DELETE FROM telemetry_events WHERE client_id = ? AND user_id = ?",
                (client_id, user_id),
            )
            profile = conn.execute(
                "DELETE FROM learner_profiles WHERE client_id = ? AND user_id = ?",
                (client_id, user_id),
            )
            return len(session_ids) + max(profile.rowcount, 0)

    def export_telemetry(
        self, client_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        return self.telemetry.export_telemetry(client_id=client_id, limit=limit)


class TursoDatabase(Database):
    """Remote Turso implementation of the repository database contract."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if get_settings().database_backend.lower() != "turso":
            raise ValueError("Set GAME_LOOP_DATABASE_BACKEND=turso to construct TursoDatabase")
        super().__init__(db_path)


_db_instance: Database | None = None


def get_database(db_path: Path | str | None = None) -> Database:
    global _db_instance
    settings = get_settings()
    expected_type = TursoDatabase if settings.database_backend.lower() == "turso" else Database
    if _db_instance is None or db_path is not None or type(_db_instance) is not expected_type:
        _db_instance = expected_type(db_path)
    return _db_instance
